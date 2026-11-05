"""Durable owner-bound authorization; external work never retains a SQL transaction."""

from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

import jwt

from app.ai.github_projects import GitHubProjectClient
from app.core.errors import ApplicationError
from app.core.github_credentials import GitHubCredentialVault, reauthorize
from app.core.github_settings import GitHubSettings
from app.domain.clock import Clock, utc_now
from app.repositories.github_projects import (
    GitHubAuthorizationGrant,
    GitHubConnectionLease,
    GitHubProjectRepository,
)
from app.schemas.github_projects import (
    ConnectionView,
    InstallationComplete,
    InstallationStart,
    InstallationView,
    RepositoryView,
)


class GitHubAuthorizationService:
    def __init__(
        self,
        repository: GitHubProjectRepository,
        settings: GitHubSettings,
        client: GitHubProjectClient,
        clock: Clock = utc_now,
    ) -> None:
        self.repository, self.settings, self.client, self.clock = (
            repository,
            settings,
            client,
            clock,
        )
        self._vault = (
            GitHubCredentialVault(settings.token_encryption_key)
            if settings.mode == "enabled"
            else None
        )

    def _enabled(self) -> GitHubCredentialVault:
        if self._vault is None:
            raise ApplicationError(
                "github_not_configured", "GitHub App owner configuration is required.", 503
            )
        return self._vault

    def start(self, owner: UUID) -> InstallationStart:
        self._enabled()
        now, state_id = self.clock(), uuid4()
        expiry = now + timedelta(minutes=10)
        self.repository.reserve_state(owner, state_id, expiry)
        state = jwt.encode(
            {
                "jti": str(state_id),
                "sub": str(owner),
                "iss": "trace-github-installation",
                "aud": "trace-project-learning",
                "exp": int(expiry.timestamp()),
            },
            self.settings.state_signing_secret.get_secret_value(),
            algorithm="HS256",
        )
        authorization = "https://github.com/login/oauth/authorize?" + urlencode(
            {
                "client_id": self.settings.client_id,
                "state": state,
                "redirect_uri": self.settings.callback_url,
            }
        )
        return InstallationStart(
            installation_url=(
                f"https://github.com/apps/{self.settings.slug}/installations/new?"
                + urlencode({"state": state})
            ),
            authorization_url=authorization,
            state=state,
            expires_at=expiry,
        )

    def _consume(self, owner: UUID, state: str) -> None:
        try:
            claims = jwt.decode(
                state,
                self.settings.state_signing_secret.get_secret_value(),
                algorithms=["HS256"],
                audience="trace-project-learning",
                issuer="trace-github-installation",
                options={"verify_exp": False, "require": ["jti", "sub", "exp", "iss", "aud"]},
            )
            state_id = UUID(claims["jti"])
            if claims["sub"] != str(owner) or claims["exp"] <= self.clock().timestamp():
                raise ValueError()
        except Exception:
            raise ApplicationError(
                "github_state_invalid", "Restart GitHub authorization.", 409
            ) from None
        if not self.repository.consume_state(owner, state_id, self.clock()):
            raise ApplicationError("github_state_invalid", "Restart GitHub authorization.", 409)

    def complete(self, owner: UUID, body: InstallationComplete) -> InstallationView:
        vault = self._enabled()
        self._consume(owner, body.state)
        started = self.clock()
        credential = self.client.exchange_authorization(body.code)
        if type(credential.expires_in) is not int or not 0 < credential.expires_in <= 28800:
            raise reauthorize()
        token = credential.access_token
        user_id = self.client.user_id(token)
        installations = self.client.accessible_installations(token)
        installation = body.installation_id
        if installation is None:
            if not installations:
                raise ApplicationError(
                    "github_installation_missing", "No accessible GitHub App installation.", 404
                )
            if len(installations) != 1:
                raise ApplicationError(
                    "github_installation_selection_required",
                    "Select a GitHub App installation and authorize again.",
                    409,
                )
            installation = installations[0]
        elif installation not in installations:
            raise ApplicationError(
                "github_installation_inaccessible", "GitHub installation access is denied.", 403
            )
        self.client.validate_installation(installation)
        repositories = self.client.accessible_repositories(token, installation)
        now = self.clock()
        expiry = started + timedelta(seconds=credential.expires_in)
        if expiry <= now:
            raise reauthorize()
        ciphertext = vault.encrypt(owner, installation, user_id, token, expiry)
        self.repository.bind_installation(
            owner,
            installation,
            user_id,
            [item.repository_id for item in repositories],
            now,
            token_ciphertext=ciphertext,
            credential_expires_at=expiry,
        )
        return InstallationView(
            installation_id=installation,
            authorization_expires_at=expiry,
            status="authorized",
        )

    def installations(self, owner: UUID) -> tuple[InstallationView, ...]:
        results = []
        for identity in self.repository.installations(owner):
            grant = self.repository.authorization_grant(owner, identity)
            if grant is None:
                continue
            active = (
                grant.disconnected_at is None
                and grant.credential_expires_at is not None
                and grant.credential_expires_at > self.clock()
                and bool(grant.token_ciphertext)
            )
            results.append(
                InstallationView(
                    installation_id=identity,
                    authorization_expires_at=grant.credential_expires_at if active else None,
                    status="authorized"
                    if active
                    else "disconnected"
                    if grant.disconnected_at is not None
                    else "reauthorization_required",
                )
            )
        return tuple(results)

    def _repositories(
        self, owner: UUID, installation: int
    ) -> tuple[GitHubAuthorizationGrant, tuple[RepositoryView, ...]]:
        vault = self._enabled()
        grant = self.repository.authorization_grant(owner, installation)
        if grant is None:
            raise ApplicationError("not_found", "Connection not found.", 404)
        if (
            grant.disconnected_at is not None
            or grant.credential_expires_at is None
            or grant.credential_expires_at <= self.clock()
        ):
            raise reauthorize()
        token = vault.decrypt(grant)
        self.client.validate_installation(installation)
        repositories = self.client.accessible_repositories(token, installation)
        current = self.repository.authorization_grant(owner, installation)
        if (
            current is None
            or current.authorization_revision != grant.authorization_revision
            or current.disconnected_at is not None
            or current.credential_expires_at is None
            or current.credential_expires_at <= self.clock()
        ):
            raise reauthorize()
        allowed = set(grant.repository_ids)
        return grant, tuple(item for item in repositories if item.repository_id in allowed)

    def repositories(self, owner: UUID, installation: int) -> tuple[RepositoryView, ...]:
        return self._repositories(owner, installation)[1]

    def connect(self, owner: UUID, installation: int, repository_id: int) -> ConnectionView:
        grant, repositories = self._repositories(owner, installation)
        chosen = next((item for item in repositories if item.repository_id == repository_id), None)
        if chosen is None:
            raise ApplicationError("not_found", "Repository is not authorized.", 404)
        return self.repository.connect(
            owner,
            installation,
            chosen,
            self.clock(),
            authorization_revision=grant.authorization_revision,
        )

    def authorize_connection(self, owner: UUID, identity: UUID) -> GitHubConnectionLease:
        lease = self.repository.connection_lease(owner, identity)
        if lease.connection.status != "connected":
            raise ApplicationError("not_found", "Connection not found.", 404)
        grant, allowed = self._repositories(owner, lease.connection.installation_id)
        if (
            grant.authorization_revision != lease.authorization_revision
            or not any(
                item.repository_id == lease.connection.repository_id
                and item.full_name == lease.connection.full_name
                for item in allowed
            )
            or not self.repository.lease_current(lease, self.clock())
        ):
            raise ApplicationError("not_found", "Repository is not authorized.", 404)
        return lease

    def assert_authorization(self, owner: UUID, lease: GitHubConnectionLease) -> None:
        if owner != lease.owner_id:
            raise ApplicationError("not_found", "Connection not found.", 404)
        fresh = self.authorize_connection(owner, UUID(lease.connection.id))
        if fresh != lease:
            raise ApplicationError(
                "github_access_changed", "GitHub access changed. Reconnect.", 409
            )

    def disconnect_installation(self, owner: UUID, installation: int) -> InstallationView:
        # Disconnect is local and works during GitHub outages or disabled mode.
        # It wipes the encrypted bearer and invalidates all in-flight leases.
        self.repository.disconnect_installation(owner, installation, self.clock())
        return InstallationView(installation_id=installation, status="disconnected")

    def disconnect_connection(self, owner: UUID, identity: UUID) -> ConnectionView:
        return self.repository.disconnect_connection(owner, identity, self.clock())
