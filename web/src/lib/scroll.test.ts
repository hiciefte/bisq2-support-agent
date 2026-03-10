import { scrollWindowToTop } from "./scroll";

describe("scrollWindowToTop", () => {
  test("scrolls window to top with smooth behavior by default", () => {
    const scrollSpy = jest.spyOn(window, "scrollTo").mockImplementation(() => {});

    scrollWindowToTop();

    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
    scrollSpy.mockRestore();
  });

  test("supports explicit behavior", () => {
    const scrollSpy = jest.spyOn(window, "scrollTo").mockImplementation(() => {});

    scrollWindowToTop("auto");

    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: "auto" });
    scrollSpy.mockRestore();
  });
});
