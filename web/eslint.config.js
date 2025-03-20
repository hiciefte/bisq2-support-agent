import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
    baseDirectory: __dirname,
});

const eslintConfig = [
    ...compat.extends("next/core-web-vitals", "next/typescript"),
    {
        rules: {
            "@typescript-eslint/no-explicit-any": "error",
            "@typescript-eslint/no-unused-vars": "error",
            "quotes": ["error", "double"],
            "indent": ["error", 4],
            "jsx-quotes": ["error", "prefer-double"],
            "semi": ["error", "always"],
            "comma-dangle": ["error", "always-multiline"],
            "arrow-parens": ["error", "always"]
        },
    },
];

export default eslintConfig; 