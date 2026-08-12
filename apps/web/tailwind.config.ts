import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(220 13% 88%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(222 20% 12%)",
        muted: "hsl(220 14% 96%)",
        "muted-foreground": "hsl(220 9% 40%)",
        primary: "hsl(222 47% 16%)",
        "primary-foreground": "hsl(0 0% 100%)",
      },
      borderRadius: {
        lg: "0.5rem",
        md: "0.375rem",
        sm: "0.25rem",
      },
    },
  },
  plugins: [],
};

export default config;
