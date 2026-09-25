import { candidateEvaluationLabel } from "./evaluation-state";

test("missing evaluation is distinct from a genuine zero score", () => {
  expect(candidateEvaluationLabel({ generated_answer: null, final_score: null })).toBe("Not evaluated");
  expect(candidateEvaluationLabel({ generated_answer: "answer", final_score: null })).toBe("Comparison generated · not scored");
  expect(candidateEvaluationLabel({ generated_answer: "answer", final_score: 0 })).toBe("Comparison score: 0%");
});
