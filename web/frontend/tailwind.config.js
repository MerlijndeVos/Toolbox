/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        chrome: "hsl(var(--chrome))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        danger: {
          DEFAULT: "hsl(var(--danger))",
          text: "hsl(var(--danger-text))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          text: "hsl(var(--warning-text))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          text: "hsl(var(--success-text))",
        },
        overlay: "hsl(var(--overlay))",
        log: {
          info: "hsl(var(--log-info))",
          warn: "hsl(var(--log-warn))",
          error: "hsl(var(--log-error))",
        },
        syntax: {
          keyword: "hsl(var(--syntax-keyword))",
          string: "hsl(var(--syntax-string))",
          number: "hsl(var(--syntax-number))",
          comment: "hsl(var(--syntax-comment))",
          function: "hsl(var(--syntax-function))",
          type: "hsl(var(--syntax-type))",
          property: "hsl(var(--syntax-property))",
          meta: "hsl(var(--syntax-meta))",
        },
        category: {
          files: "hsl(var(--category-files))",
          media: "hsl(var(--category-media))",
          subtitles: "hsl(var(--category-subtitles))",
          experimental: "hsl(var(--category-experimental))",
          other: "hsl(var(--category-other))",
          settings: "hsl(var(--category-settings))",
          foreground: "hsl(var(--category-foreground))",
        },
      },
      fontFamily: {
        sans: "var(--font-sans)",
        mono: ["\"Geist Mono\"", "ui-monospace", "\"Cascadia Mono\"", "Menlo", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};
