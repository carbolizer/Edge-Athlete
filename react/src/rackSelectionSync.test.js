import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// A SOURCE-LEVEL test, and deliberately so.
//
// The bug it guards: the effect that pushes a locally-chosen movement to the server
// used to depend on `controller.snapshot`. Tapping a movement pushes to the server
// WITHOUT setting local state, so local holds the old value until the snapshot
// round-trips back — and that arriving snapshot re-ran the effect while local was
// still stale, pushing the OLD movement back and undoing the tap. Every time.
//
// ⚠️ WHY NOT A BEHAVIOURAL TEST. This suite renders with renderToStaticMarkup,
// which never runs effects at all, so nothing here can observe an effect loop. The
// bug shipped twice — once undiagnosed, once diagnosed but incompletely fixed —
// precisely because a fully green suite says nothing about it.
//
// So this asserts the one thing that actually went wrong: the dependency array. It
// fails if someone "tidies up" the eslint-disable by adding the dep back, which is
// exactly how this would return.
describe("the movement-selection sync effect", () => {
  const source = readFileSync(
    new URL("./rack/RackScreen.jsx", import.meta.url),
    "utf8",
  );

  // The whole effect block, found by its body rather than a line number: walk back
  // from the push call to the useEffect that owns it, forward to its dep array.
  const push = source.indexOf(
    "controller.updateState({ selected_exercise: selectedExerciseId })",
  );
  const effect = source.slice(
    source.lastIndexOf("useEffect(() => {", push),
    source.indexOf("])", push) + 2,
  );
  const deps = effect.slice(effect.indexOf("}, ["));

  it("does not re-run when a new snapshot arrives", () => {
    expect(deps).not.toContain("controller.snapshot");
  });

  it("still re-runs when the local selection changes", () => {
    // Without this it would never push the default chosen at check-in, and the
    // server would not learn which movement the athlete is on.
    expect(deps).toContain("selectedExerciseId");
  });

  it("keeps reading the snapshot to skip a redundant write", () => {
    // Reading is fine and wanted — it is DEPENDING on it that caused the loop.
    expect(effect.slice(0, effect.indexOf("}, ["))).toContain(
      "controller.snapshot?.selected_exercise?.id === selectedExerciseId",
    );
  });
});
