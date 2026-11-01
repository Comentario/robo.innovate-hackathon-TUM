#!/bin/sh
# Show the demo page full screen on a monitor attached to the Jetson: Firefox ESR in kiosk
# mode as a Wayland client of the WendyOS compositor (`display` entitlement in wendy.json).
# Without a Wayland socket (headless image, no monitor) it waits and checks again, so the
# page is still served to other computers on port $PORT.
PORT="${PORT:-8000}"
URL="http://127.0.0.1:${PORT}/#present"

wayland_socket() {
    case "$WAYLAND_DISPLAY" in
        "") return 1 ;;
        /*) [ -S "$WAYLAND_DISPLAY" ] ;;
        *) [ -S "${XDG_RUNTIME_DIR:-/nonexistent}/$WAYLAND_DISPLAY" ] ;;
    esac
}

until wayland_socket; do
    echo "kiosk: no Wayland display yet (WAYLAND_DISPLAY='${WAYLAND_DISPLAY}'), checking again in 30 s"
    sleep 30
done
until python3 -c "import socket; socket.create_connection(('127.0.0.1', ${PORT}), 1)" 2>/dev/null; do
    sleep 2
done

# Fresh profile on every start: no first-run pages, no session restore, software rendering
# (the page is a video stream and text; it does not need the GPU, which the detector uses).
PROFILE=/tmp/kiosk-profile
rm -rf "$PROFILE" && mkdir -p "$PROFILE"
cat > "$PROFILE/user.js" <<'EOF'
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.translations.automaticallyPopup", false);
user_pref("full-screen-api.warning.timeout", 0);
user_pref("gfx.webrender.software", true);
user_pref("network.captive-portal-service.enabled", false);
EOF

while true; do
    echo "kiosk: opening $URL on the attached monitor"
    # The container cannot create user namespaces, so Firefox's sandbox is off (it only
    # opens this local page).
    MOZ_ENABLE_WAYLAND=1 HOME=/tmp MOZ_DISABLE_CONTENT_SANDBOX=1 MOZ_DISABLE_RDD_SANDBOX=1 \
        MOZ_DISABLE_SOCKET_PROCESS_SANDBOX=1 MOZ_DISABLE_GMP_SANDBOX=1 \
        firefox-esr --kiosk --no-remote --profile "$PROFILE" "$URL"
    echo "kiosk: browser exited ($?), starting it again in 3 s"
    sleep 3
done
