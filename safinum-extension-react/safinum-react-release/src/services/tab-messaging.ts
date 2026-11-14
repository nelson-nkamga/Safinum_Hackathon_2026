import type { TabMessage } from "../types/translation";

// Le content script n'est pas toujours prêt immédiatement; si la page est chargée
// sans injection automatique, on réinjecte le script de contenu puis on réessaie.
export async function sendToTab<T>(tabId: number, msg: TabMessage, retries = 3): Promise<T | null> {
  let attempt = 0;
  while (attempt <= retries) {
    try {
      return (await chrome.tabs.sendMessage(tabId, msg)) as T;
    } catch {
      if (attempt === retries) {
        try {
          await chrome.scripting.executeScript({
            target: { tabId },
            files: ["content.js"]
          });
          for (let i = 0; i <= 2; i += 1) {
            try {
              return (await chrome.tabs.sendMessage(tabId, msg)) as T;
            } catch {
              await new Promise((resolve) => setTimeout(resolve, 250));
            }
          }
        } catch {
          // no-op: on laisse le popup afficher un message explicite de compatibilité.
        }
        return null;
      }
      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  return null;
}
