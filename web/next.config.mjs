const api = process.env.DFO_API_URL || "http://127.0.0.1:8000";
export default {
  experimental: {proxyTimeout: 55000},
  async rewrites() {
    return [{source: "/api/:path*", destination: api + "/api/:path*"}];
  }
};
