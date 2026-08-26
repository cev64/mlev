package com.mlev.app;

import java.lang.reflect.Method;

/**
 * Runs MainActivity.normalise on a desktop JVM.
 *
 * The Activity itself cannot be instantiated off-device, but `normalise` is
 * static and dependency-free by design, and it is the one thing that decides
 * whether the app can reach your computer at all. Run with ./android/run-tests.sh.
 */
public class NormaliseTest {

    private static int failures = 0;

    public static void main(String[] args) throws Exception {
        Method m = MainActivity.class.getDeclaredMethod("normalise", String.class);
        m.setAccessible(true);

        // The three shapes people actually type.
        check(m, "192.168.1.42", "http://192.168.1.42:8733");
        check(m, "192.168.1.42:8733", "http://192.168.1.42:8733");
        check(m, "http://192.168.1.42:8733", "http://192.168.1.42:8733");

        // A non-default port must survive.
        check(m, "192.168.1.42:9001", "http://192.168.1.42:9001");

        // Pasted from a browser, with a path and whitespace.
        check(m, "  http://192.168.1.42:8733/  ", "http://192.168.1.42:8733");
        check(m, "http://192.168.1.42:8733/?tab=edge", "http://192.168.1.42:8733");

        // Hostnames, not just addresses.
        check(m, "macbook.local", "http://macbook.local:8733");
        check(m, "https://mlev.example.com", "https://mlev.example.com:8733");

        // Rubbish must be rejected rather than producing an unloadable URL.
        check(m, null, null);
        check(m, "", null);
        check(m, "   ", null);
        check(m, "192.168.1.42:notaport", null);
        check(m, "192.168.1.42:70000", null);
        check(m, "ftp://192.168.1.42", null);
        check(m, "has spaces", null);
        check(m, "http://", null);

        if (failures > 0) {
            System.out.println(failures + " FAILED");
            System.exit(1);
        }
        System.out.println("all normalise tests passed");
    }

    private static void check(Method m, String input, String expected) throws Exception {
        Object got = m.invoke(null, input);
        boolean ok = expected == null ? got == null : expected.equals(got);
        if (!ok) {
            failures++;
            System.out.println("FAIL  " + input + "  ->  " + got + "   (expected " + expected + ")");
        }
    }
}
