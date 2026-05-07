/** @type {import('next').NextConfig} */
const nextConfig = {
  // The `ws` package is Node-only and breaks under webpack's
  // module-resolution defaults. `serverExternalPackages` (renamed
  // from `experimental.serverComponentsExternalPackages` in Next 15)
  // tells the bundler to leave it alone in server bundles.
  serverExternalPackages: ["ws"],

  webpack: (config) => {
    // The lib/ + state/ + tests/ files use `.js` import suffixes — that's
    // the standard convention for Node16 module resolution and the WS2
    // package shipped with it. Bundler-mode tsc resolves these via
    // extensionAlias (tsconfig has it implicitly), but Next's webpack
    // doesn't, so we wire it up here. Otherwise build fails with
    // "Module not found: Can't resolve './chat-types.js'".
    config.resolve.extensionAlias = {
      ...config.resolve.extensionAlias,
      ".js": [".ts", ".tsx", ".js", ".jsx"],
    };
    return config;
  },
};

export default nextConfig;
