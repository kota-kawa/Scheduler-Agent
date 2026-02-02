export const highlightIds = (ids: Array<string | number> | null | undefined): void => {
  if (!Array.isArray(ids)) return;
  ids.forEach((id) => {
    const el = document.getElementById(String(id));
    if (el) {
      el.classList.remove("flash-highlight");
      void el.offsetWidth;
      el.classList.add("flash-highlight");
      setTimeout(() => el.classList.remove("flash-highlight"), 2000);
    }
  });
};
