import { createDisplay } from "./display";
import { readStepInfo } from "./step-info";
import type { TabMessage } from "../types/translation";

const display = createDisplay();

chrome.runtime.onMessage.addListener((msg: TabMessage, _sender, sendResponse) => {
  switch (msg.type) {
    case "GET_STATE":
      sendResponse(display.getState());
      return false;
    case "SET_STATE":
      display.setState(msg).then(() => sendResponse(display.getState()));
      return true;
    case "RESTORE":
      display.setState({ enabled: false, lang: null }).then(() => sendResponse(display.getState()));
      return true;
    case "GET_STEP_INFO":
      sendResponse(display.withOriginals(readStepInfo));
      return false;
  }
  return false;
});
