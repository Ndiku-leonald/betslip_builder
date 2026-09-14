import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: { colors: { ink: "#09111f", panel: "#101b2e", line: "#24334a", mint: "#74f0c1", amber: "#f5c46b" } } },
  plugins: [],
};

export default config;

