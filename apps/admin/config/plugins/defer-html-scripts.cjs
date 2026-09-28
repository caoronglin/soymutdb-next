/**
 * Umi's webpack entry assets are added with `addHTMLHeadScripts`, which emits
 * blocking `<script src>` tags into <head>. The app entry calls `createRoot`
 * during evaluation, so `document.getElementById('root')` is still null while
 * <head> is parsed and React throws #299 ("Target container is not a DOM
 * element") -- a blank page in both dev and the built artifact.
 *
 * `modifyHTML` is the supported hook for the final document. Deferring is the
 * smallest change that preserves execution order.
 */
module.exports = (api) => {
  api.modifyHTML(($) => {
    $("head script[src]").each((_, element) => {
      const script = $(element);
      if (!script.attr("defer") && !script.attr("async")) script.attr("defer", "");
    });
    return $;
  });
};
