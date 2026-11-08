import "./style.css";
import { h } from "./dom";
import { renderHistory, renderReplay } from "./history";
import { renderMatch } from "./match";
import { renderSetup } from "./setup";

// Hash routes: "#/" = setup, "#/match/<id>" = spectate, "#/match/<id>/<player>" = play a seat,
// "#/history" = saved matches, "#/replay/<id>" = step through a saved match.
const app = document.querySelector<HTMLDivElement>("#app")!;
const main = h("main");
app.replaceChildren(h("header", {}, h("a", { href: "#/", class: "brand" }, "● Nim AI Arena"), " ", h("a", { href: "#/history", class: "nav" }, "History")), main);

let dispose: () => void = () => {};

function route() {
  dispose();
  const [, section, matchId, playerId] = location.hash.replace(/^#/, "").split("/").map(decodeURIComponent);
  if (section === "match" && matchId) {
    dispose = renderMatch(main, matchId, playerId || null);
  } else if (section === "history") {
    dispose = renderHistory(main);
  } else if (section === "replay" && matchId) {
    dispose = renderReplay(main, matchId);
  } else {
    dispose = renderSetup(main);
  }
}

window.addEventListener("hashchange", route);
route();
