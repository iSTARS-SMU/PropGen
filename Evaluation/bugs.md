# Detected Bugs

PropGen found 25 previously unknown functional bugs across 8 of the 12 subject apps using the generated properties.

| ID | App | Description |
|---|---|---|
| 1 | OmniNotes | Info dialog fails to display metadata (e.g., word/char count) for empty text notes. |
| 2 | OmniNotes | Reminder day labels (e.g., MON, FRI) become invisible when selected in the custom reminder dialog. |
| 3 | OmniNotes | Category default color changes unexpectedly when the user navigates color-picker tabs without confirming. |
| 4 | OmniNotes | Navigation drawer does not dismiss when the user taps the currently active item. |
| 5 | OmniNotes | Photo captured immediately after recording audio fails to appear in the note. |
| 6 | OmniNotes | The attachment menu is not dismissed when the user switches to the sketch screen, causing a UI overlay. |
| 7 | OmniNotes | Reminder icon does not appear in the note list immediately after a reminder is created via the context menu. |
| 8 | OmniNotes | An existing image attachment is silently deleted when the user discards changes after a reminder notification fires. |
| 9 | OmniNotes | A new attachment is silently dropped when added immediately after deleting the previous one. |
| 10 | OmniNotes | Floating action button incorrectly appears on the Reminders screen after the user navigates back from Settings. |
| 11 | RetroMusic | A deleted song remains visible in the Most Played list until the user navigates away and returns. |
| 12 | RetroMusic | Edited lyrics are not reflected in the UI until the user leaves and re-enters the lyrics page. |
| 13 | RetroMusic | A deleted song continues to appear in the History list until the user navigates away and returns. |
| 14 | RetroMusic | A newly set artist image is not displayed until the user navigates away and returns to the artist page. |
| 15 | RetroMusic | Resetting an artist image has no visible effect until the user leaves and re-enters the artist page. |
| 16 | RetroMusic | Updated album art is reflected in song lists but not in the active mini-player or main player. |
| 17 | Amaze | Deleting a folder on an SD card shows a "Done" notification but the folder is not actually removed. |
| 18 | OuterTune | Navigating to the Songs tab from the History tab requires two taps instead of one. |
| 19 | MaterialFiles | The file list is not refreshed after the user clears search input, leaving stale filtered results. |
| 20 | MaterialFiles | Creating a file inside a JAR archive displays a raw Java exception toast instead of a user-friendly error. |
| 21 | MaterialFiles | Deleting a folder and then accessing a stale breadcrumb entry shows a raw Java exception toast. |
| 22 | uhabits | Entering a very large number causes integer overflow, corrupting data and breaking chart rendering. |
| 23 | Orgzly | Importing a non-JSON file displays a raw Java parsing exception instead of a clear error message. |
| 24 | Markor | The Star icon state does not update when the Favourite checkbox is toggled (one-way sync only). |
| 25 | Markor | The "Insert Image" feature inserts Markdown syntax into plain `.txt` files where it has no effect. |
