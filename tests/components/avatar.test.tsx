import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { Avatar } from "@/components/avatar/avatar";
import { AvatarPicker } from "@/components/avatar/avatar-picker";
import { AVATARS, AVATAR_IDS, defaultAvatarId, isAvatarId, resolveAvatarId } from "@/lib/avatars/avatars";
import { displayNameFrom, FALLBACK_NAME } from "@/lib/avatars/profile";

const fx = vi.hoisted(() => ({ updateUser: vi.fn(), getSession: vi.fn() }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => ({ auth: { updateUser: fx.updateUser, getSession: fx.getSession } }) }));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  fx.updateUser.mockResolvedValue({ error: null });
});

test("the set is original, sized 12 to 16, and the default is deterministic and never a letter", () => {
  expect(AVATARS.length).toBeGreaterThanOrEqual(12);
  expect(AVATARS.length).toBeLessThanOrEqual(16);
  expect(new Set(AVATAR_IDS).size).toBe(AVATARS.length);
  expect(defaultAvatarId("user-1")).toBe(defaultAvatarId("user-1"));
  const spread = new Set(Array.from({ length: 60 }, (_, i) => defaultAvatarId(`user-${i}`)));
  expect(spread.size).toBeGreaterThan(6);
  const { container } = render(<Avatar seed="user-1" />);
  expect(container.textContent).toBe("");
  expect(screen.getByRole("img", { name: "Avatar" })).toHaveAttribute("data-avatar", defaultAvatarId("user-1"));
});

test("an id outside the allowlist is ignored on read and write", async () => {
  expect(isAvatarId("apricot-round")).toBe(true);
  for (const bad of ["../../etc", "<svg onload=1>", "", null, 5, "https://evil.example/a.png"]) expect(isAvatarId(bad)).toBe(false);
  expect(resolveAvatarId("not-an-avatar", "seed")).toBe(defaultAvatarId("seed"));
  render(<Avatar avatarId="<script>" seed="seed" />);
  expect(screen.getByRole("img", { name: "Avatar" })).toHaveAttribute("data-avatar", defaultAvatarId("seed"));
  const { saveAvatar } = await import("@/lib/avatars/profile");
  await expect(saveAvatar("u", "evil")).rejects.toThrow();
  expect(fx.updateUser).not.toHaveBeenCalled();
});

test("avatar images: only HTTPS, no referrer, and a drawn fallback on error", () => {
  const { rerender } = render(<Avatar seed="u" src="http://insecure.example/a.png" />);
  expect(document.querySelector("img")).toBeNull();
  rerender(<Avatar seed="u" src="https://cdn.example/a.png" />);
  const img = document.querySelector("img")!;
  expect(img).toHaveAttribute("referrerpolicy", "no-referrer");
  expect(img).toHaveAttribute("alt", "Avatar");
  img.dispatchEvent(new Event("error"));
  return waitFor(() => expect(screen.getByRole("img", { name: "Avatar" }).tagName.toLowerCase()).toBe("svg"));
});

test("a skeleton shows while the avatar loads, and the name never comes from the email", () => {
  const { container } = render(<Avatar seed="u" loading />);
  expect(container.querySelector(".skeleton")).not.toBeNull();
  expect(displayNameFrom({ full_name: "  Ada Lovelace " })).toBe("Ada Lovelace");
  expect(displayNameFrom({ name: "ada@example.test" })).toBe(FALLBACK_NAME);
  expect(displayNameFrom({ email: "ada@example.test" })).toBe(FALLBACK_NAME);
  expect(displayNameFrom(null)).toBe(FALLBACK_NAME);
});

test("the picker is a dialog you can drive by keyboard, previews, saves to the account, and closes with Escape", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  render(<AvatarPicker userId="user-1" current={null} onClose={onClose} />);
  const dialog = screen.getByRole("dialog", { name: "Choose your avatar" });
  const group = within(dialog).getByRole("group", { name: "Avatars" });
  const choices = within(group).getAllByRole("button");
  expect(choices).toHaveLength(AVATARS.length);
  const start = choices.findIndex((button) => button.getAttribute("aria-pressed") === "true");
  expect(start).toBeGreaterThanOrEqual(0);
  choices[start].focus();
  await user.keyboard("{ArrowRight}");
  expect(choices[Math.min(start + 1, choices.length - 1)]).toHaveFocus();
  await user.keyboard("{End}");
  expect(choices.at(-1)).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(choices.at(-1)).toHaveAttribute("aria-pressed", "true");
  await user.click(within(dialog).getByRole("button", { name: "Save avatar" }));
  expect(fx.updateUser).toHaveBeenCalledWith({ data: { avatar_id: AVATAR_IDS.at(-1) } });
  expect(await within(dialog).findByText("Saved to your account.")).toBeVisible();
  expect(JSON.parse(localStorage.getItem("trace.avatar.user-1")!)).toEqual({ id: AVATAR_IDS.at(-1), onlyHere: false });
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});

test("if the account can't be updated the choice stays on this device and the dialog says so", async () => {
  const user = userEvent.setup();
  fx.updateUser.mockResolvedValue({ error: { message: "network" } });
  render(<AvatarPicker userId="user-2" current="apricot-round" onClose={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Sage leaf" }));
  await user.click(screen.getByRole("button", { name: "Save avatar" }));
  expect(await screen.findByText("Saved on this device. Your account couldn't be updated right now.")).toBeVisible();
  expect(JSON.parse(localStorage.getItem("trace.avatar.user-2")!)).toEqual({ id: "sage-leaf", onlyHere: true });
  fx.updateUser.mockRejectedValue(new Error("offline"));
  await user.click(screen.getByRole("button", { name: "Save avatar" }));
  expect(await screen.findByText(/Saved on this device/)).toBeVisible();
});
