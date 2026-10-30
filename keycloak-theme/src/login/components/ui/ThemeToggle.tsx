import { Moon, Sun } from "lucide-react";
import { useTheme } from "../../../components/ThemeProvider";
import { Button } from "../../../components/ui/button";

export function ModeToggle() {
    const { theme, setTheme } = useTheme();

    // "system" resolves to the OS preference, so the first click always changes the page.
    const isDark =
        theme === "dark" ||
        (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);

    const toggleTheme = () => setTheme(isDark ? "light" : "dark");

    return (
        <Button
            variant="outline"
            size="icon"
            onClick={toggleTheme}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
            <Sun className="h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
        </Button>
    );
}
