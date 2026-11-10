/* global I18n */
I18n.ready.then(() => I18n.applyTranslations(document)).catch(() => {
  // The shared loader provides a bilingual retry screen on failure.
});
