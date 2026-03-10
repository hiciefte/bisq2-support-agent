export function scrollWindowToTop(behavior: ScrollBehavior = "smooth"): void {
  if (typeof window === "undefined" || typeof window.scrollTo !== "function") {
    return;
  }

  window.scrollTo({ top: 0, behavior });
}
