// Meta fallback proxy. Vercel serves existing static meta files first
// (filesystem beats rewrites), so this only runs for ids we DON'T carry:
// upstream-only titles found via Global Search. Pure upstream passthrough.
// Route (see vercel.json): /meta/:type/:id -> /api/meta?type=:type&id=:id

const UPSTREAM =
  "https://catalog.nuvio.tv/%7B%22language%22%3A%22es-MX%22%2C%22region%22%3A%22CR%22%7D" +
  "/meta";

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  try {
    const type = String((req.query && req.query.type) || "").replace(/\.json$/, "");
    const id = String((req.query && req.query.id) || "").replace(/\.json$/, "");
    if ((type !== "movie" && type !== "series") || !id) {
      return res.status(200).json({ meta: null });
    }
    const upstream = await fetch(
      `${UPSTREAM}/${type}/${encodeURIComponent(id)}.json`,
      { headers: { "User-Agent": "NuvioFeed-meta-proxy/1.0" } }
    );
    if (!upstream.ok) return res.status(200).json({ meta: null });
    const data = await upstream.json();
    res.setHeader("Cache-Control", "public, s-maxage=86400, stale-while-revalidate=3600");
    return res.status(200).json(data && data.meta ? { meta: data.meta } : { meta: null });
  } catch (e) {
    return res.status(200).json({ meta: null });
  }
};
