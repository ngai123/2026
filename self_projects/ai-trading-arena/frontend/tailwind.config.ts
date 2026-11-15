import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Anthropic brand palette
        brand: {
          dark: "#141413", // primary text / dark surfaces
          light: "#faf9f5", // page background
          mid: "#b0aea5", // secondary elements
          subtle: "#e8e6dc", // borders / subtle fills
          card: "#ffffff", // card surface
          muted: "#73726c", // readable secondary text
          orange: "#d97757", // primary accent
          blue: "#6a9bcc", // secondary accent
          green: "#788c5d", // tertiary accent
        },
      },
      fontFamily: {
        heading: ["var(--font-poppins)", "Poppins", "Arial", "sans-serif"],
        body: ["var(--font-lora)", "Lora", "Georgia", "serif"],
      },
    },
  },
  plugins: [],
};

export default config;
