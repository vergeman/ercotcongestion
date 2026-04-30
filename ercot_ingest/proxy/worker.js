const ERCOT_API = "https://api.ercot.com";
const ERCOT_TOKEN = "https://ercotb2c.b2clogin.com";


export default {
    async fetch(request, env) {

        /* local guard - make sure randoms can't trigger */
        const auth = request.headers.get("X-Proxy-Auth");
        if (auth !== env.WRANGLER_PROXY_SECRET) {
            return new Response("Unauthorized", { status: 401 });
        }

        const url = new URL(request.url);
        let target;

        /*
          /token: POST request to /token URL; pass ERCOT Creds in request body to get token
          /api: uses acquired bearer token above with Subscription Key in Headers to make API request
         */
        if (url.pathname.startsWith("/token")) {
            target = ERCOT_TOKEN + url.pathname.replace(/^\/token/, "") + url.search;
        } else if (url.pathname.startsWith("/api")) {
            target = ERCOT_API + url.pathname + url.search;
        } else {
            return new Response("Not found", { status: 404 });
        }

        /* repackage headers */
        const headers = new Headers(request.headers);
        headers.delete("X-Proxy-Auth");
        headers.delete("Host");

        const upstream = await fetch(target, {
            method: request.method,
            headers,
            body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        });

        return new Response(upstream.body, {
            status: upstream.status,
            headers: upstream.headers,
        });
    },
};
