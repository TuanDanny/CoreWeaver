"""Canonical shared hardware contract fragments."""

APB_SLAVE_INTERFACE = {
    "signals": [
        {"name": "psel_i", "dir": "input", "width": 1},
        {"name": "penable_i", "dir": "input", "width": 1},
        {"name": "pwrite_i", "dir": "input", "width": 1},
        {"name": "paddr_i", "dir": "input", "width": 32},
        {"name": "pwdata_i", "dir": "input", "width": 32},
        {"name": "prdata_o", "dir": "output", "width": 32},
        {"name": "pready_o", "dir": "output", "width": 1},
        {"name": "pslverr_o", "dir": "output", "width": 1},
    ],
    "naming_rule": "All slaves use IDENTICAL signal names. Master prefixes with 'm_'.",
}
