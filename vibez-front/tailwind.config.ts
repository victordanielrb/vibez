import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx,js,jsx,mdx}"],
  theme: {
    extend: {
      colors: {
        vibez: {
          purple: "#7C3AED",
          pink: "#EC4899",
          dark: "#0F0F0F",
        },
      },
    },
  },
  plugins: [],
};

export default config;
