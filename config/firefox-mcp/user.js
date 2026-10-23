// firefox-devtools-mcp quiet profile: the browser contacts only the sites it is sent to.
// Each group names what it stops. Tested on Firefox 150.0.1 (2026-10-23).

// HTTP/3 (QUIC over UDP) off, so every connection is TCP and visible to a proxy or capture.
user_pref("network.http.http3.enable", false);

// Captive portal and connectivity checks (detectportal.firefox.com).
user_pref("network.captive-portal-service.enabled", false);
user_pref("network.connectivity-service.enabled", false);
// The error page and a background check still fetch the canonical URL; empty it.
user_pref("captivedetect.canonicalURL", "");

// Remote settings (firefox.settings.services.mozilla.com) and its signature chain
// (content-signature-2.cdn.mozilla.net). Pointing the server at a dead local port
// stops every collection sync, including CRLite, intermediates, blocklists and Nimbus.
// Release builds honour this pref only with MOZ_REMOTE_SETTINGS_DEVTOOLS=1 in Firefox's env
// (scripts/firefox-mcp.sh passes it); without it the pref is silently ignored.
user_pref("services.settings.server", "http://127.0.0.1:9/v1");
user_pref("security.remote_settings.crlite_filters.enabled", false);
user_pref("security.remote_settings.intermediates.enabled", false);
user_pref("extensions.blocklist.enabled", false);
user_pref("messaging-system.rsexperimentloader.enabled", false);
user_pref("browser.translations.enable", false);
user_pref("browser.ml.enable", false);

// Studies, Normandy, Nimbus.
user_pref("app.normandy.enabled", false);
user_pref("app.normandy.api_url", "");
user_pref("app.shield.optoutstudies.enabled", false);

// Telemetry and health report.
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("toolkit.telemetry.server", "data:,");
// Glean (FOG) still sends a one-off deletion-request ping to incoming.telemetry.mozilla.org
// when upload is off. A negative test port makes its uploader pretend and send nothing.
user_pref("telemetry.fog.test.localhost_port", -1);
user_pref("toolkit.telemetry.newProfilePing.enabled", false);
user_pref("toolkit.telemetry.shutdownPingSender.enabled", false);
user_pref("toolkit.telemetry.updatePing.enabled", false);
user_pref("toolkit.telemetry.bhrPing.enabled", false);
user_pref("toolkit.telemetry.firstShutdownPing.enabled", false);
user_pref("toolkit.coverage.opt-out", true);
user_pref("toolkit.coverage.endpoint.base", "");
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.usage.uploadEnabled", false);
user_pref("browser.ping-centre.telemetry", false);
user_pref("browser.newtabpage.activity-stream.feeds.telemetry", false);
user_pref("browser.newtabpage.activity-stream.telemetry", false);

// Safe Browsing (Google) and tracking-protection list updates.
user_pref("browser.safebrowsing.malware.enabled", false);
user_pref("browser.safebrowsing.phishing.enabled", false);
user_pref("browser.safebrowsing.downloads.enabled", false);
user_pref("browser.safebrowsing.downloads.remote.enabled", false);
user_pref("browser.safebrowsing.blockedURIs.enabled", false);
user_pref("browser.safebrowsing.provider.google4.updateURL", "");
user_pref("browser.safebrowsing.provider.google.updateURL", "");
user_pref("browser.safebrowsing.provider.mozilla.updateURL", "");
user_pref("browser.safebrowsing.update.enabled", false);

// Region lookup, geolocation, search-engine updates.
user_pref("browser.region.network.url", "");
user_pref("browser.region.update.enabled", false);
user_pref("geo.enabled", false);
user_pref("geo.provider.network.url", "");
user_pref("browser.search.update", false);

// Speculative connections and prefetch (connections to sites not yet visited).
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.predictor.enabled", false);
user_pref("network.http.speculative-parallel-limit", 0);
user_pref("browser.urlbar.speculativeConnect.enabled", false);
user_pref("browser.places.speculativeConnect.enabled", false);
user_pref("browser.urlbar.quicksuggest.enabled", false);
user_pref("browser.urlbar.suggest.quicksuggest.sponsored", false);
user_pref("browser.urlbar.suggest.quicksuggest.nonsponsored", false);

// DNS-over-HTTPS off (mozilla.cloudflare-dns.com); use the system resolver.
user_pref("network.trr.mode", 5);

// OCSP queries go to the certificate's CA, a third party. Stapled OCSP still works.
user_pref("security.OCSP.enabled", 0);

// Push service (push.services.mozilla.com).
user_pref("dom.push.enabled", false);
user_pref("dom.push.connection.enabled", false);
user_pref("dom.push.serverURL", "");

// Updates: app, add-ons, system add-ons, plugins (OpenH264/Widevine).
user_pref("app.update.auto", false);
user_pref("app.update.disabledForTesting", true);
user_pref("extensions.update.enabled", false);
user_pref("extensions.getAddons.cache.enabled", false);
user_pref("extensions.systemAddon.update.enabled", false);
user_pref("extensions.systemAddon.update.url", "");
user_pref("media.gmp-manager.url", "");
user_pref("media.gmp-gmpopenh264.enabled", false);
user_pref("media.gmp-widevinecdm.enabled", false);
user_pref("media.eme.enabled", false);

// New tab / home page content (top sites, Pocket, sponsored tiles).
user_pref("browser.startup.homepage", "about:blank");
user_pref("browser.startup.page", 0);
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.newtabpage.activity-stream.feeds.topsites", false);
user_pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);
user_pref("browser.newtabpage.activity-stream.feeds.system.topstories", false);
user_pref("browser.newtabpage.activity-stream.showSponsored", false);
user_pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);
user_pref("browser.topsites.contile.enabled", false);
user_pref("extensions.pocket.enabled", false);
user_pref("browser.discovery.enabled", false);
user_pref("extensions.htmlaboutaddons.recommendations.enabled", false);
