/**
 * Theme provider — light/dark toggle persisted to localStorage and reflected
 * via the `data-theme` attribute on <html>.
 */
import * as React from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "soymutdb-theme";

interface ThemeContextValue {
    theme: Theme;
    setTheme: (next: Theme) => void;
    toggleTheme: () => void;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

function readStoredTheme(): Theme {
    if (typeof localStorage === "undefined") return "light";
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
    // Fall back to OS preference.
    if (typeof window !== "undefined" && window.matchMedia) {
        return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    return "light";
}

function applyTheme(theme: Theme): void {
    if (typeof document === "undefined") return;
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    const [theme, setThemeState] = React.useState<Theme>(() => readStoredTheme());

    React.useEffect(() => {
        applyTheme(theme);
    }, [theme]);

    const setTheme = React.useCallback((next: Theme) => {
        setThemeState(next);
        if (typeof localStorage !== "undefined") {
            localStorage.setItem(STORAGE_KEY, next);
        }
    }, []);

    const toggleTheme = React.useCallback(() => {
        setThemeState((prev) => {
            const next = prev === "light" ? "dark" : "light";
            applyTheme(next);
            if (typeof localStorage !== "undefined") {
                localStorage.setItem(STORAGE_KEY, next);
            }
            return next;
        });
    }, []);

    const value = React.useMemo(
        () => ({ theme, setTheme, toggleTheme }),
        [theme, setTheme, toggleTheme],
    );

    return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
    const ctx = React.useContext(ThemeContext);
    if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
    return ctx;
}
