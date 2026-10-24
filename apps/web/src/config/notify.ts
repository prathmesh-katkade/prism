import { isTauriRuntime } from "./runtime";

/**
 * Fire a native OS notification for a background result worth surfacing
 * even if the user has switched to another workflow tab -- never called on
 * the plain web/Render build, where there's no OS-level surface for it and
 * the in-page UI state is the only notice. Permission is requested lazily
 * (not at app startup) since the first real notification is also the first
 * moment one is actually needed.
 */
export async function notifyDesktop(title: string, body: string): Promise<void> {
  if (!isTauriRuntime()) return;
  const { isPermissionGranted, requestPermission, sendNotification } = await import("@tauri-apps/plugin-notification");
  const granted = (await isPermissionGranted()) || (await requestPermission()) === "granted";
  if (granted) sendNotification({ title, body });
}
