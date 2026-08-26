package com.mlev.app;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

/**
 * A thin native shell around the mlev web app running on your computer.
 *
 * The models need Python, pandas and about a hundred megabytes of data, so they
 * cannot run on the phone. This app is the client: you point it at the machine
 * running `Start mlev.command` and it renders the same interface full screen,
 * with a real app icon and no browser chrome.
 *
 * It exists rather than a home-screen shortcut for one concrete reason: an
 * installable PWA needs a secure context, and a computer on your Wi-Fi serves
 * plain HTTP. A WebView has no such requirement.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "mlev";
    private static final String KEY_SERVER = "server";
    private static final int DEFAULT_PORT = 8733;

    private WebView web;
    private FrameLayout root;
    private ProgressBar progress;
    private boolean showingError = false;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#f4f4f2"));
        setContentView(root);

        String server = prefs().getString(KEY_SERVER, null);
        if (server == null || server.isEmpty()) {
            showSetup(null);
        } else {
            showWeb(server);
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    // ---------------------------------------------------------------- setup

    /** Asks for the computer's address. Shown on first run and after a failure. */
    private void showSetup(String message) {
        root.removeAllViews();
        showingError = false;

        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setGravity(Gravity.CENTER_VERTICAL);
        int pad = dp(24);
        column.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Connect to mlev");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 24);
        title.setTextColor(Color.parseColor("#0b0b0b"));
        column.addView(title);

        TextView blurb = new TextView(this);
        blurb.setText(message != null ? message
                : "On your computer, start mlev with network access:\n\n"
                + "    Start mlev.command --lan\n\n"
                + "It prints an address like http://192.168.1.42:8733 — "
                + "type it below. Both devices need to be on the same Wi-Fi.");
        blurb.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        blurb.setTextColor(Color.parseColor("#52514e"));
        blurb.setPadding(0, dp(12), 0, dp(20));
        column.addView(blurb);

        final EditText field = new EditText(this);
        field.setHint("192.168.1.42:8733");
        field.setSingleLine(true);
        field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        field.setImeOptions(EditorInfo.IME_ACTION_GO);
        String previous = prefs().getString(KEY_SERVER, "");
        if (!previous.isEmpty()) {
            field.setText(previous);
        }
        column.addView(field);

        Button connect = new Button(this);
        connect.setText("Connect");
        connect.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { connect(field.getText().toString()); }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(16);
        column.addView(connect, lp);

        field.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int actionId, android.view.KeyEvent e) {
                if (actionId == EditorInfo.IME_ACTION_GO) {
                    connect(field.getText().toString());
                    return true;
                }
                return false;
            }
        });

        root.addView(column);
    }

    private void connect(String typed) {
        String url = normalise(typed);
        if (url == null) {
            Toast.makeText(this, "That does not look like an address", Toast.LENGTH_SHORT).show();
            return;
        }
        prefs().edit().putString(KEY_SERVER, url).apply();
        showWeb(url);
    }

    /**
     * Turns what someone actually types into a URL.
     *
     * People type "192.168.1.42", "192.168.1.42:8733", "http://…", or paste
     * something with a trailing slash. All of those should work, and the default
     * port is filled in when it is missing.
     *
     * Deliberately plain string handling rather than android.net.Uri, so this —
     * the one piece of logic in the app that can stop it connecting at all — can
     * be unit-tested on a desktop JVM. See NormaliseTest.
     */
    static String normalise(String input) {
        if (input == null) return null;
        String text = input.trim();
        if (text.isEmpty()) return null;

        String scheme = "http";
        int schemeEnd = text.indexOf("://");
        if (schemeEnd >= 0) {
            scheme = text.substring(0, schemeEnd).toLowerCase();
            if (!scheme.equals("http") && !scheme.equals("https")) return null;
            text = text.substring(schemeEnd + 3);
        }

        // Drop any path, query or fragment — we only want host and port.
        int cut = text.length();
        for (String marker : new String[] {"/", "?", "#"}) {
            int at = text.indexOf(marker);
            if (at >= 0 && at < cut) cut = at;
        }
        text = text.substring(0, cut).trim();
        if (text.isEmpty()) return null;

        String host = text;
        int port = DEFAULT_PORT;
        int colon = text.lastIndexOf(':');
        if (colon >= 0) {
            host = text.substring(0, colon);
            String portText = text.substring(colon + 1);
            if (!portText.isEmpty()) {
                try {
                    port = Integer.parseInt(portText);
                } catch (NumberFormatException e) {
                    return null;
                }
                if (port < 1 || port > 65535) return null;
            }
        }

        if (host.isEmpty()) return null;
        for (int i = 0; i < host.length(); i++) {
            char c = host.charAt(i);
            boolean allowed = Character.isLetterOrDigit(c) || c == '.' || c == '-' || c == '_';
            if (!allowed) return null;
        }
        return scheme + "://" + host + ":" + port;
    }

    // ------------------------------------------------------------------ web

    private void showWeb(final String server) {
        root.removeAllViews();
        showingError = false;

        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        // The app keeps typed prices and the offline snapshot in localStorage,
        // which is off by default in a WebView.
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportZoom(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // Keep our own pages inside the app; hand anything else to the browser.
                android.net.Uri target = request.getUrl();
                android.net.Uri home = android.net.Uri.parse(server);
                String host = home.getHost();
                if (host != null && host.equals(target.getHost())) return false;
                try {
                    startActivity(new android.content.Intent(
                            android.content.Intent.ACTION_VIEW, target));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request.isForMainFrame()) showFailure(server);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (progress != null) progress.setVisibility(View.GONE);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int value) {
                if (progress != null) {
                    progress.setProgress(value);
                    progress.setVisibility(value >= 100 ? View.GONE : View.VISIBLE);
                }
            }
        });

        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        root.addView(progress, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(3), Gravity.TOP));

        if (!online()) {
            // Offline is not necessarily fatal: the page caches its last numbers.
            Toast.makeText(this, "No network — showing whatever was cached",
                    Toast.LENGTH_LONG).show();
        }
        web.loadUrl(server);
    }

    private void showFailure(String server) {
        if (showingError) return;
        showingError = true;
        showSetup("Could not reach " + server + ".\n\n"
                + "Check that:\n"
                + "  • mlev is running on your computer\n"
                + "  • it was started with --lan\n"
                + "  • both devices are on the same Wi-Fi\n"
                + "  • the address below is right\n\n"
                + "Your computer's address can change when it rejoins a network.");
    }

    private boolean online() {
        try {
            ConnectivityManager cm =
                    (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            NetworkInfo info = cm.getActiveNetworkInfo();
            return info != null && info.isConnected();
        } catch (Exception e) {
            return true;   // if we cannot tell, try anyway
        }
    }

    // -------------------------------------------------------------- chrome

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    /** Volume-down twice is a hidden way back to the setup screen if the IP moves. */
    @Override
    public boolean onKeyDown(int keyCode, android.view.KeyEvent event) {
        if (keyCode == android.view.KeyEvent.KEYCODE_VOLUME_DOWN && event.isLongPress()) {
            showSetup("Change the address mlev connects to.");
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
