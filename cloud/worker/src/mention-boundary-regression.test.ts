import {expect, it} from "vitest";
import {matchesAppMention} from "./webhook";

it.each(["foo**@slug**", "@slug**bot**"])("formatting does not create a token boundary: %s", body => {
  expect(matchesAppMention(body, "slug")).toBe(false);
});
