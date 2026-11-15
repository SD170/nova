// Best-effort parsing of LinkedIn feed posts that are ALREADY on screen.
// LinkedIn renames things often: every selector lives here so a break is a one-file
// fix. Pure DOM in, plain objects out (no chrome.* APIs) so it can be tested on a
// saved HTML page (test/parse-test.html).
//
// Two layouts are supported:
//  - NEW (seen 2026-11-15, "SDUI"): scrambled class names, no urn. Stable hooks are
//    role/aria-label/data-testid/componentkey attributes:
//      post      div[role=listitem][componentkey*="FeedType_"]
//      author    button[aria-label="Open control menu for post by <name>"]
//      text      [data-testid=expandable-text-box]
//      buttons   aria-label "Reaction button state: ...", "Comment", "Repost";
//                data-testid=expandable-text-button for "… more"
//  - OLD: data-urn="urn:li:activity:..." + update-components-* classes.
/* exported JarvisParse */
const JarvisParse = (() => {
  const NEW_POST = 'div[role="listitem"][componentkey*="FeedType_"]';
  const OLD_POST = [
    'div[data-urn^="urn:li:activity:"]',
    'div[data-urn^="urn:li:share:"]',
    'div[data-urn^="urn:li:ugcPost:"]',
    'div[data-id^="urn:li:activity:"]',
  ];
  const POST_SELECTOR = [NEW_POST, ...OLD_POST].join(", ");

  // old layout
  const NAME = [
    '.update-components-actor__title span[aria-hidden="true"]',
    '.update-components-actor__name span[aria-hidden="true"]',
    ".update-components-actor__title",
    ".feed-shared-actor__name",
  ];
  const HEADLINE = [
    '.update-components-actor__description span[aria-hidden="true"]',
    ".update-components-actor__description",
    ".feed-shared-actor__description",
  ];
  const BODY = [
    '[data-testid="expandable-text-box"]',
    ".update-components-text",
    ".feed-shared-update-v2__description",
    ".feed-shared-inline-show-more-text",
    ".feed-shared-text",
  ];
  const ACTOR_LINK = [
    "a.update-components-actor__meta-link",
    "a.update-components-actor__image",
    '.update-components-actor a[href*="/in/"]',
    '.update-components-actor a[href*="/company/"]',
  ];
  const PROFILE_LINK = 'a[href*="/in/"], a[href*="/company/"]';
  const MENU_PREFIX = "open control menu for post by ";
  // lines under the author name that are not the headline
  const NOT_HEADLINE = /^(•\s*)?((1st|2nd|3rd\+?|following|promoted|follow|verified)\b.*|\d+[smhdwy]\b.*|edited\b.*|[\d,.]+\s*followers?)$/i;

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const textOf = (el) => (el ? clean(el.innerText || el.textContent) : "");

  function pick(root, selectors) {
    for (const sel of selectors) {
      const el = root.querySelector(sel);
      if (el && textOf(el)) return el;
    }
    return null;
  }

  function postId(el) {
    const urn = el.getAttribute("data-urn") || el.getAttribute("data-id");
    if (urn) return urn;
    const key = el.getAttribute("componentkey");
    if (!key) return null;
    // "update-card-focusf-XXXXFeedType_MAIN_FEED_RELEVANCE" -> "li:f-XXXX"
    const core = key.replace(/^update-card-focus/, "").replace(/FeedType_.*$/, "");
    return core ? "li:" + core : null;
  }

  function cleanName(s) {
    // "Priya Raman • 2nd" / "Priya Raman Verified" / "Priya RamanPriya Raman"
    let n = clean(s).split(" • ")[0].replace(/\b(Verified|Premium)\b.*$/i, "").trim();
    const half = n.length / 2;
    if (n.length % 2 === 0 && n.slice(0, half) === n.slice(half)) n = n.slice(0, half);
    return n;
  }

  function cleanUrl(href) {
    if (!href) return null;
    try {
      const u = new URL(href, location.origin);
      return u.origin + u.pathname;
    } catch (_) {
      return null;
    }
  }

  function bodyText(el) {
    const box = pick(el, BODY);
    if (!box) return "";
    const copy = box.cloneNode(true);
    copy.querySelectorAll('button, [data-testid="expandable-text-button"]').forEach((b) => b.remove());
    // detached clones have no innerText layout: keep line breaks as spaces
    copy.querySelectorAll("br").forEach((b) => b.replaceWith(" "));
    return textOf(copy).replace(/…\s*(see )?more$/i, "").trim();
  }

  // NEW layout: name from the control-menu button, then the author link/headline
  // are the profile link and <p> lines that come right after it (skipping the
  // "X likes this / follows this page" header, which sits before an <hr>).
  function parseNew(el) {
    const menu = [...el.querySelectorAll("button[aria-label]")]
      .find((b) => b.getAttribute("aria-label").toLowerCase().startsWith(MENU_PREFIX));
    const name = menu ? cleanName(menu.getAttribute("aria-label").slice(MENU_PREFIX.length)) : "";
    if (!name) return null;

    const box = el.querySelector('[data-testid="expandable-text-box"]');
    const inBody = (n) => box && box.contains(n);
    const hr = el.querySelector('hr[role="presentation"]');
    const afterHeader = (n) => !hr || (hr.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING);

    const links = [...el.querySelectorAll(PROFILE_LINK)].filter((a) => !inBody(a) && afterHeader(a));
    const nameLink = links.find((a) => textOf(a).toLowerCase().startsWith(name.toLowerCase()))
      || links.find((a) => (a.querySelector("img[alt]") || {}).alt && a.querySelector("img").alt.includes(name))
      || links[0];

    let headline = "";
    if (nameLink) {
      const ps = [...el.querySelectorAll("p")].filter((p) => !inBody(p) && !(box && p.contains(box)));
      for (const p of ps) {
        if (!(nameLink.compareDocumentPosition(p) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
        if (nameLink.contains(p)) continue;
        const t = textOf(p);
        if (!t || t.toLowerCase().startsWith(name.toLowerCase()) || NOT_HEADLINE.test(t)) continue;
        headline = t;
        break;
      }
    }
    return { author_name: name, author_headline: headline,
             author_url: cleanUrl(nameLink && nameLink.getAttribute("href")) };
  }

  function parseOld(el) {
    const author_name = cleanName(textOf(pick(el, NAME)));
    if (!author_name) return null;
    const link = ACTOR_LINK.map((s) => el.querySelector(s)).find(Boolean);
    return { author_name, author_headline: textOf(pick(el, HEADLINE)),
             author_url: cleanUrl(link && link.getAttribute("href")) };
  }

  function parsePost(el) {
    const id = postId(el);
    if (!id) return null;
    const author = el.matches(NEW_POST) ? (parseNew(el) || parseOld(el)) : parseOld(el);
    if (!author) return null;
    return {
      id,
      ...author,
      text: bodyText(el).slice(0, 4000),
      post_url: id.startsWith("urn:li:activity:") ? `https://www.linkedin.com/feed/update/${id}/` : null,
    };
  }

  // What kind of engagement a click on `target` inside a post is, or null.
  function clickKind(target) {
    const btn = target.closest("button, a");
    if (!btn) return null;
    const label = (btn.getAttribute("aria-label") || "").toLowerCase();
    const testid = btn.getAttribute("data-testid") || "";
    const cls = typeof btn.className === "string" ? btn.className : "";
    const txt = textOf(btn).toLowerCase();
    if (testid === "expandable-text-button" || cls.includes("see-more")
        || /(^|\s)(…|\.\.\.)?\s*(see )?more$/.test(txt)) return "expanded";
    if (label.startsWith("reaction button state")) {
      return label.includes("no reaction") ? "liked" : null; // un-react isn't interest
    }
    if (cls.includes("react-button") || label.startsWith("react like") || label === "like") {
      return btn.getAttribute("aria-pressed") === "true" ? null : "liked";
    }
    if (cls.includes("comment-button") || label === "comment" || label.startsWith("comment on")) return "commented";
    if (label.startsWith("repost") || cls.includes("social-reshare-button")) return "reposted";
    if (btn.matches(ACTOR_LINK.join(", "))) return "profile_click";
    if (btn.matches(PROFILE_LINK) && !btn.closest('[data-testid="expandable-text-box"]')) return "profile_click";
    return null;
  }

  return { POST_SELECTOR, parsePost, clickKind, postId };
})();
