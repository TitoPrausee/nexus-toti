---
name: minecraft-mod-client-feedback
description: Ensure Minecraft Fabric mods give visible feedback to the player on world join — avoid Thread.sleep, use tick-based delays and chat messages.
version: 1.0.0
---

# Minecraft Mod — Client Feedback Pitfalls

## Problem
Fabric mods that silently initialize with no visible feedback confuse and frustrate users. The mod loads, users see nothing, and assume it's broken.

## Critical: NEVER use `Thread.sleep()` on the client thread

**WRONG — blocks the entire render thread, screen never opens:**
```java
client.execute(() -> {
    Thread.sleep(1500);  // ❌ BLOCKS Minecraft's render thread!
    client.setScreen(new WelcomeGuideScreen(true));
});
```

**RIGHT — use tick-based delay:**
```java
client.execute(() -> {
    final int[] ticksToWait = {30}; // ~1.5 seconds at 20 TPS
    ClientTickEvents.END_CLIENT_TICK.register(tickClient -> {
        ticksToWait[0]--;
        if (ticksToWait[0] > 0) return;
        if (tickClient.player == null) return;
        tickClient.setScreen(new WelcomeGuideScreen(true));
    });
});
```

## Always add a chat message on world join

Every mod should show a visible confirmation when the player joins a world:

```java
ClientPlayConnectionEvents.JOIN.register((handler, sender, client) -> {
    client.execute(() -> {
        final int[] ticksToWait = {10};
        ClientTickEvents.END_CLIENT_TICK.register(tickClient -> {
            ticksToWait[0]--;
            if (ticksToWait[0] > 0) return;
            if (tickClient.player == null) return;
            
            // Visible chat message — essential!
            tickClient.player.sendMessage(
                Text.literal("§8[§c☭§8] §7Mod Name §av" + getModVersion() + "§7 active!"),
                false  // false = in chat, true = action bar
            );
        });
    });
});
```

## Get mod version dynamically
```java
private static String getModVersion() {
    try {
        return net.fabricmc.loader.api.FabricLoader.getInstance()
            .getModContainer("your_mod_id")
            .map(c -> c.getMetadata().getVersion().getFriendlyString())
            .orElse("?");
    } catch (Exception e) {
        return "?";
    }
}
```

## Title Screen Badge — INSTANT proof the mod loaded

The MOST reliable way to prove a mod loaded: add a ButtonWidget to the title screen. The user sees it before even creating a world.

### Setup: Mixin config

In `src/main/resources/mixins.yourmod.json`:
```json
{
  "required": true,
  "minVersion": "0.8",
  "package": "com.yourmod.mixin",
  "compatibilityLevel": "JAVA_21",
  "mixins": [],
  "client": ["TitleScreenMixin"],
  "injectors": { "defaultRequire": 1 }
}
```

### Template: TitleScreenMixin.java

```java
package com.yourmod.mixin;

import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.TitleScreen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Adds a visible badge to the title screen proving the mod loaded.
 * Seen immediately when launching the game, at the bottom-left.
 */
@Mixin(TitleScreen.class)
public abstract class TitleScreenMixin {

    @Shadow
    protected abstract <T extends net.minecraft.client.gui.Element 
        & net.minecraft.client.gui.Drawable 
        & net.minecraft.client.gui.Selectable> T addDrawableChild(T drawableElement);

    @Shadow
    public int height;

    @Unique
    private boolean badgeAdded = false;

    @Inject(method = "init", at = @At("TAIL"))
    private void onInit(CallbackInfo ci) {
        if (badgeAdded) return;
        badgeAdded = true;

        ButtonWidget badge = ButtonWidget.builder(
                Text.literal("§c☭ §7Your Mod §av1.0.0"),
                btn -> {}
        )
                .dimensions(2, this.height - 20, 170, 18)
                .build();

        this.addDrawableChild(badge);
    }
}
```

**The `@Shadow` fields are critical:** `addDrawableChild` is `protected` in `Screen`, and `height` is a field on `Screen`. Extending `Screen` in a mixin causes diamond inheritance issues — using `@Shadow` avoids that entirely.

**Why this works when everything else fails:**
- TitleScreen is loaded IMMEDIATELY when the game starts
- If the Mixin applies, the mod IS running — no room for doubt
- The badge is visible before clicking anything

## Emergency: Mod won't start at all?

If the mod crashes during init and Minecraft won't even reach the title screen, a **TitleScreenMixin won't help** — the mod never gets there.

**Solution:** Wrap `onInitialize()` and `onInitializeClient()` in try-catch with a CrashHandler that uses **AWT/Swing** (runs on its own thread, independent of LWJGL). Minecraft starts anyway, the error is shown in a popup.

See skill: **`minecraft-mod-crash-handler`** for the complete implementation.

## Patterns summary

| Pattern | ❌ Don't | ✅ Do |
|---------|----------|-------|
| First proof mod loaded | Silent init, hope for the best | **TitleScreen Mixin** — badge on main menu |
| Screen delay | `Thread.sleep()` | Tick counter via `ClientTickEvents` |
| Show mod is active in-game | Silent join | Chat message on `JOIN` event |
| Version in message | Hardcode string | `FabricLoader.getModContainer()` |
| First-time detection | `guideSeenThisSession` flag + persisted `.dat` file | Check file existence, show guide, then persist |

## Crash Handler — When the Mod PREVENTS Minecraft from Starting

Sometimes the mod crashes during `onInitialize()` or `onInitializeClient()` before reaching the title screen. The TitleScreen Mixin never fires. The user sees a black screen or Instant Crash.

### Solution: try-catch + AWT/Swing popup

Wrap all initialization code in try-catch. On error, spawn a **separate AWT/Swing window** (before Minecraft's GLFW/LWJGL starts) showing the error.

```java
// In WorkersCollective.java (server-side init)
@Override
public void onInitialize() {
    try {
        // ... all your registry calls ...
    } catch (Throwable t) {
        LOGGER.error("FATAL initialization error!", t);
        CrashHandler.showCrash("onInitialize (Main/Server)", t);
        // Do NOT re-throw — Minecraft still starts partially
    }
}

// In WorkersCollectiveClient.java (client-side init)
@Override
public void onInitializeClient() {
    try {
        // ... all your screen registrations ...
    } catch (Throwable t) {
        LOGGER.error("FATAL client init error!", t);
        CrashHandler.showCrash("onInitializeClient (Client)", t);
    }
}
```

### The CrashHandler class

Create `CrashHandler.java` in your mod package:

```java
package com.yourmod;

import javax.swing.*;
import java.awt.*;
import java.io.*;
import java.nio.file.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
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
        // Build: header → error type → full stacktrace → cause chain → last 50 log lines
        StringBuilder sb = new StringBuilder();
        sb.append("FATAL STARTUP ERROR\n");
        sb.append("Time:  ").append(LocalDateTime.now()).append("\n");
        sb.append("Phase: ").append(phase).append("\n");
        sb.append("Error: ").append(error.getClass().getName()).append("\n\n");
        
        // Stacktrace
        StringWriter sw = new StringWriter();
        error.printStackTrace(new PrintWriter(sw));
        sb.append("STACK TRACE:\n").append(sw).append("\n\n");
        
        // Caused by chain
        Throwable cause = error;
        int level = 0;
        while ((cause = cause.getCause()) != null) {
            sb.append("Caused by (level ").append(++level).append("):\n");
            sw = new StringWriter();
            cause.printStackTrace(new PrintWriter(sw));
            sb.append(sw).append("\n");
        }
        
        // Last 50 log lines
        sb.append("\nLAST 50 LINES FROM MINECRAFT LOG:\n");
        sb.append(readLatestLogLines(50)).append("\n");
        
        return sb.toString();
    }

    private static String readLatestLogLines(int count) {
        String[] candidates = {
            "logs/latest.log", "../logs/latest.log",
            System.getProperty("user.home") + "/logs/latest.log"
        };
        for (String path : candidates) {
            try {
                Path f = Paths.get(path);
                if (Files.exists(f)) {
                    var lines = Files.readAllLines(f);
                    return String.join("\n", lines.subList(
                        Math.max(0, lines.size() - count), lines.size()));
                }
            } catch (Exception ignored) {}
        }
        return "(log not found)";
    }

    private static void saveCrashReport(String report) {
        try {
            Path dir = Paths.get("crash-reports");
            Files.createDirectories(dir);
            String ts = LocalDateTime.now()
                .format(DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss"));
            Files.writeString(dir.resolve("crash-" + ts + ".txt"), report);
        } catch (Exception ignored) {}
    }

    private static void showSwingWindow(String report, Throwable error, String phase) {
        try {
            UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName());
        } catch (Exception ignored) {}
        
        JFrame frame = new JFrame("☭ Mod Name — Startup Error");
        frame.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
        frame.setSize(900, 680);
        frame.setAlwaysOnTop(true);
        frame.setLocationRelativeTo(null);

        // Red header
        JPanel header = new JPanel(new BorderLayout());
        header.setBackground(new Color(180, 20, 20));
        header.setBorder(BorderFactory.createEmptyBorder(12, 16, 12, 16));
        JLabel title = new JLabel("FATAL STARTUP ERROR — " + phase);
        title.setForeground(Color.WHITE);
        title.setFont(new Font("SansSerif", Font.BOLD, 16));
        header.add(title);

        // Error summary
        JLabel errorLabel = new JLabel(
            "⚠ " + error.getClass().getSimpleName() + ": "
            + (error.getMessage() != null ? error.getMessage() : "(no message)"));
        errorLabel.setForeground(new Color(255, 100, 100));
        errorLabel.setBackground(new Color(40, 40, 40));
        errorLabel.setOpaque(true);
        errorLabel.setBorder(BorderFactory.createEmptyBorder(8, 16, 8, 16));

        // Terminal-style text area
        JTextArea textArea = new JTextArea(report);
        textArea.setEditable(false);
        textArea.setFont(new Font("Monospaced", Font.PLAIN, 11));
        textArea.setBackground(Color.BLACK);
        textArea.setForeground(new Color(0, 220, 0));

        // Close + Copy buttons
        JButton closeBtn = new JButton("Close (Minecraft continues with partial load)");
        closeBtn.setBackground(new Color(180, 20, 20));
        closeBtn.setForeground(Color.WHITE);
        closeBtn.addActionListener(e -> frame.dispose());

        JButton copyBtn = new JButton("Copy Error Report");
        copyBtn.addActionListener(e -> {
            Toolkit.getDefaultToolkit().getSystemClipboard()
                .setContents(new java.awt.datatransfer.StringSelection(report), null);
            copyBtn.setText("Copied!");
        });

        JPanel buttons = new JPanel();
        buttons.add(copyBtn);
        buttons.add(closeBtn);

        frame.setLayout(new BorderLayout());
        frame.add(header, BorderLayout.NORTH);
        frame.add(errorLabel, BorderLayout.NORTH); // second north
        frame.add(new JScrollPane(textArea), BorderLayout.CENTER);
        frame.add(buttons, BorderLayout.SOUTH);
        frame.setVisible(true);
        frame.toFront();
    }
}
```

### Key design decisions

| Decision | Reason |
|----------|--------|
| **AWT/Swing** not LWJGL | LWJGL hasn't initialized yet during mod init — AWT is always available |
| **`setAlwaysOnTop(true)`** | Ensures the window isn't hidden behind Minecraft's (possibly blank) screen |
| **Do NOT re-throw** | If you re-throw, Fabric shuts down Minecraft. By catching, the mod is partially loaded but Minecraft starts. User sees both the error window AND the game. |
| **Save to file** | In case the window is closed accidentally, the report persists in `crash-reports/` |
| **Only show ONCE** | `static boolean shown` prevents spamming multiple error windows |
| **Read Minecraft log** | `logs/latest.log` — the most useful diagnostic data the user can provide |
| **Cause chain** | The root cause is often 2-3 levels deep in the exception chain |

### Testing

To simulate a crash and verify the handler works:

```java
// Temporarily add this to your init to test
if (true) throw new RuntimeException("Test crash — this popup should appear!");
```

Then run the mod locally. The popup should appear with the full error report.
