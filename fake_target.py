"""
Fake stash window for E2E testing.

Simulates a PoE-like window: left-click advances through a fixed list of item
texts; Ctrl+C copies the current item to the clipboard (as PoE would).

Run standalone or let test_e2e.py launch it as a subprocess.
"""
import sys
import tkinter as tk

ITEMS = [
    # 0 — plain, nothing desirable
    """\
Item Class: Maps
Rarity: Normal
Tower Map
--------
Area Level: 80
--------
Item Quantity: +5%
Item Rarity: +6%""",

    # 1 — has Pack Size → desirable (matches inclusion rule)
    """\
Item Class: Maps
Rarity: Magic
Packed Tower Map
--------
Area Level: 80
--------
Item Quantity: +22%
Item Rarity: +15%
Monster Pack Size: +28%""",

    # 2 — has Reflect → excluded (matches exclusion rule)
    """\
Item Class: Maps
Rarity: Magic
Reflected Tower Map
--------
Area Level: 80
--------
Reflects 14 Physical Damage to Melee Attackers
Monster Pack Size: +12%""",

    # 3 — plain again
    """\
Item Class: Maps
Rarity: Normal
Tower Map
--------
Area Level: 80""",
]


def main():
    root = tk.Tk()
    root.title("FakeStash")
    root.geometry("440x200")
    root.resizable(False, False)
    root.configure(bg="#1a1a1a")

    idx = [0]

    lbl = tk.Label(
        root, text=ITEMS[0], justify="left", anchor="nw",
        font=("Consolas", 9), bg="#1a1a1a", fg="#c8c8c8",
        padx=12, pady=8,
    )
    lbl.pack(fill="both", expand=True)

    footer = tk.Label(root, text="item 0 of 4", font=("Consolas", 8),
                      bg="#111", fg="#666")
    footer.pack(fill="x")

    def advance(_event=None):
        idx[0] = (idx[0] + 1) % len(ITEMS)
        lbl.config(text=ITEMS[idx[0]])
        footer.config(text=f"item {idx[0]} of {len(ITEMS)}")

    def on_ctrl_c(_event=None):
        root.clipboard_clear()
        root.clipboard_append(ITEMS[idx[0]])
        return "break"

    root.bind("<Button-1>", advance)
    lbl.bind("<Button-1>", advance)
    root.bind("<Control-c>", on_ctrl_c)

    root.mainloop()


if __name__ == "__main__":
    main()
