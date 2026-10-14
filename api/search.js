// Global search proxy: forwards queries to Nuvio's free catalogue search
// (live TMDB search, es-MX) and returns the metas unchanged.
// Same-host as manifest.json so Stremio/Nuvio accepts the catalog.
//
// Route (see vercel.json):
//   /catalog/movie/global-search/<extra>.json  ->  /api/search?extra=<extra>
// where <extra> looks like "search=parasite" or "search=parasite&skip=20".

const UPSTREAM =
  "https://catalog.nuvio.tv/%7B%22language%22%3A%22es-MX%22%2C%22region%22%3A%22CR%22%7D" +
  "/catalog/movie/popular-movies";

const EMPTY = { metas: [] };

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  try {
    const extra = String((req.query && req.query.extra) || "");
    const qm = extra.match(/(?:^|&)search=([^&]*)/);
    const query = qm ? decodeURIComponent(qm[1].replace(/\+/g, " ")).trim() : "";
    if (!query) {
      res.setHeader("Cache-Control", "public, s-maxage=60");
      return res.status(200).json(EMPTY);
    }
    const sm = extra.match(/(?:^|&)skip=(\d+)/);
    const skip = sm ? parseInt(sm[1], 10) : 0;

    let url = `${UPSTREAM}/search=${encodeURIComponent(query)}`;
    if (skip > 0) url += `&skip=${skip}`;
    url += ".json";

    const upstream = await fetch(url, {
      headers: { "User-Agent": "NuvioFeed-search-proxy/1.0" },
    });
    if (!upstream.ok) return res.status(200).json(EMPTY);
    const data = await upstream.json();

    // Be polite to the free upstream + fast for clients.
    res.setHeader("Cache-Control", "public, s-maxage=3600, stale-while-revalidate=3600");
    return res.status(200).json({ metas: Array.isArray(data.metas) ? data.metas : [] });
  } catch (e) {
    return res.status(200).json(EMPTY);
  }
};
