import "./style.css";
import { h } from "./dom";
import { renderMatch } from "./match";
import { renderSetup } from "./setup";

// Hash routes: "#/" = setup, "#/match/<id>" = spectate, "#/match/<id>/<player>" = play a seat.
const app = document.querySelector<HTMLDivElement>("#app")!;
const main = h("main");
app.replaceChildren(h("header", {}, h("a", { href: "#/", class: "brand" }, "● Nim AI Arena")), main);

let dispose: () => void = () => {};

function route() {
  dispose();
  const [, section, matchId, playerId] = location.hash.replace(/^#/, "").split("/").map(decodeURIComponent);
  if (section === "match" && matchId) {
    dispose = renderMatch(main, matchId, playerId || null);
  } else {
    dispose = renderSetup(main);
  }
}

window.addEventListener("hashchange", route);
route();
