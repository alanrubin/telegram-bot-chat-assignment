// Adds jest-dom matchers (toBeInTheDocument, toBeDisabled, toHaveClass, ...) to Vitest's expect.
import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView; stub it so the auto-scroll effect can run.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
