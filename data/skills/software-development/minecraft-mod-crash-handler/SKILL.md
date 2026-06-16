---
name: minecraft-mod-crash-handler
description: Add a CrashHandler system to Minecraft Fabric mods — AWT/Swing popup window on init failure, auto-log-read, crash report saving. Minecraft starts EVEN when the mod crashes.
version: 1.0.0
author: <GITHUB_USER>
---

# Minecraft Mod Crash Handler System

When a Fabric mod crashes during initialization (`onInitialize` or `onInitializeClient`), Minecraft fails to start with no useful error visible to the user. This skill adds a **try-catch wrapper + AWT/Swing popup window** that shows the exact error, stacktrace, and last log lines.

## Key Insight: AWT/Swing ≠ LWJGL/GLFW

AWT/Swing runs in its **own thread** independently of Minecraft's LWJGL/GLFW render system. Even if the main game thread is dead, an AWT window can still display. THIS is why it works when everything else fails.

## Files to Create

### 1. CrashHandler.java

```java
package com.yourmod;

import javax.swing.*;
import java.awt.*;
import java.io.*;
import java.nio.file.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.stream.Collectors;

public class CrashHandler {
    private static boolean shown = false;

    public static void showCrash(String phase, Throwable error) {
        if (shown) return;
        shown = true;
        String report = buildReport(phase, error);
        saveCrashReport(report);
        showSwingWindow(report, error, phase);
    }

    private static String buildReport(String phase, Throwable error) {
        StringBuilder sb = new StringBuilder();
        sb.append("━━ FATAL STARTUP ERROR ━━\n");
        sb.append("Phase: ").append(phase).append("\n");
        sb.append("Error: ").append(error.getClass().getName()).append("\n");
        sb.append("Msg:   ").append(error.getMessage() != null ? error.getMessage() : "(none)").append("\n\n");
        sb.append("═══ STACK TRACE ═══\n\n");
        StringWriter sw = new StringWriter();
        error.printStackTrace(new PrintWriter(sw));
        sb.append(indent(sw.toString())).append("\n\n");

        // Cause chain
        Throwable cause = error.getCause();
        int level = 0;
        while (cause != null && cause != error) {
            sb.append("═══ CAUSED BY (level ").append(++level).append(") ═══\n\n");
            sb.append(cause.getClass().getName()).append(": ").append(cause.getMessage()).append("\n");
            sw = new StringWriter();
            cause.printStackTrace(new PrintWriter(sw));
            sb.append(indent(sw.toString())).append("\n\n");
            cause = cause.getCause();
        }

        // Read latest Minecraft log
        sb.append("═══ LAST 50 LOG LINES ═══\n\n");
        String logText = readLatestLogLines(50);
        sb.append(logText != null ? indent(logText) : "(log not found)").append("\n");

        return sb.toString();
    }

    private static String indent(String text, int spaces) {
        String indent = "  ";
        return text.lines().map(l -> indent + l).collect(Collectors.joining("\n"));
    }

    private static String readLatestLogLines(int count) {
        String[] candidates = {
            "logs/latest.log", "../logs/latest.log",
            System.getProperty("user.dir") + "/logs/latest.log",
            System.getProperty("user.home") + "/.minecraft/logs/latest.log"
        };
        for (String path : candidates) {
            try {
                Path f = Paths.get(path);
                if (Files.exists(f)) {
                    List<String> lines = Files.readAllLines(f);
                    return String.join("\n", lines.subList(Math.max(0, lines.size()-count), lines.size()));
                }
            } catch (Exception ignored) {}
        }
        return null;
    }

    private static void saveCrashReport(String report) {
        try {
            Path dir = Paths.get("crash-reports");
            Files.createDirectories(dir);
            String fn = "yourmod-crash-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss")) + ".txt";
            Files.writeString(dir.resolve(fn), report);
        } catch (Exception ignored) {}
    }

    private static void showSwingWindow(String report, Throwable error, String phase) {
        try {
            UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName());
        } catch (Exception ignored) {}

        JFrame frame = new JFrame("☭ Your Mod — Startup Error");
        frame.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
        frame.setSize(900, 680);
        frame.setLocationRelativeTo(null);
        frame.setAlwaysOnTop(true);

        // Red header
        JPanel header = new JPanel(new BorderLayout());
        header.setBackground(new Color(180, 20, 20));
        header.setBorder(BorderFactory.createEmptyBorder(12, 16, 12, 16));
        JLabel title = new JLabel("Your Mod — FATAL STARTUP ERROR in: " + phase);
        title.setForeground(Color.WHITE);
        title.setFont(new Font("SansSerif", Font.BOLD, 16));
        header.add(title);

        // Error summary
        JLabel errLabel = new JLabel("⚠ " + error.getClass().getSimpleName() + ": " + (error.getMessage() != null ? error.getMessage() : "(no message)"));
        errLabel.setForeground(new Color(255, 100, 100));
        errLabel.setFont(new Font("Monospaced", Font.BOLD, 12));
        JPanel summary = new JPanel(new BorderLayout());
        summary.setBackground(new Color(40, 40, 40));
        summary.setBorder(BorderFactory.createEmptyBorder(8, 16, 8, 16));
        summary.add(errLabel);

        // Terminal-style text area
        JTextArea text = new JTextArea(report);
        text.setEditable(false);
        text.setFont(new Font("Monospaced", Font.PLAIN, 11));
        text.setBackground(Color.BLACK);
        text.setForeground(new Color(0, 220, 0));

        JScrollPane scroll = new JScrollPane(text);
        scroll.setBorder(BorderFactory.createLineBorder(new Color(60, 60, 60)));

        // Buttons
        JButton closeBtn = new JButton("✕ Close (Minecraft will still start)");
        closeBtn.addActionListener(e -> frame.dispose());

        frame.setLayout(new BorderLayout());
        frame.add(header, BorderLayout.NORTH);
        frame.add(scroll, BorderLayout.CENTER);
        frame.add(closeBtn, BorderLayout.SOUTH);
        frame.setVisible(true);
        frame.toFront();
    }
}
```

## 2. Wrapping `onInitialize()` in WorkersCollective.java

```java
@Override
public void onInitialize() {
    try {
        // ALL your init code here
        ModBlocks.register();
        ModItems.register();
        // ... everything ...
    } catch (Throwable t) {
        LOGGER.error("☭ FATAL initialization error!", t);
        CrashHandler.showCrash("onInitialize (Main/Server)", t);
        LOGGER.error("☭ Init FAILED — mod partially loaded. See popup window.");
        // Do NOT re-throw — Minecraft will STILL START
    }
}
```

## 3. Wrapping `onInitializeClient()` in WorkersCollectiveClient.java

Same pattern — wrap ALL code in try-catch Throwable.

## Critical Decisions

| Decision | Why |
|----------|-----|
| **DO NOT re-throw** | If you re-throw, Fabric kills the game. Catch → show error → let Minecraft start |
| **AWT/Swing (not LWJGL)** | AWT runs on its own thread. LWJGL/GLFW is dead when Minecraft crashes. AWT still works. |
| **`setAlwaysOnTop(true)`** | Ensures the error is visible even if Minecraft tries to render a blank screen |
| **Save report to file** | In case the user closes the window before reading — the report is on disk |
| **Read latest.log** | Shows the Fabric/remap errors that triggered the crash — more useful than just the Java stacktrace |

## Pitfalls

- **`Thread.sleep()` blocks AWT repaint** — don't use it anywhere near the crash handler
- **Static initializer can run before Minecraft is ready** — keep CrashHandler simple, no heavy imports
- **`.minecraft` may be elsewhere** — try multiple paths for `latest.log`
- **AWT headless mode** — on servers with no display, Swing doesn't work. The try-catch still saves the report file and console output
- **JVM crashes (SIGSEGV)** — can't be caught. This only handles Java-level Throwables
- **AWT can't init on Wayland without XWayland** — rare on gaming machines, most run X11/XWayland
