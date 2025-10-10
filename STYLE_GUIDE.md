# Code Style Guide

This document outlines the coding standards and style guidelines for the Bisq2 Support Agent project.

## Formatting Standards

### General
- **Indentation**: 4 spaces (not tabs)
- **Line endings**: LF (Unix-style)
- **Max line length**: 100 characters for TypeScript/JavaScript
- **File encoding**: UTF-8
- **Trailing whitespace**: Removed
- **Final newline**: Required in all files

### TypeScript/JavaScript
- **Quotes**: Double quotes (`"`) for strings and JSX attributes
- **Semicolons**: Required
- **Arrow functions**: Always use parentheses, even for single parameters: `(param) => { }`
- **JSX attributes**: Each on a separate line for better readability
- **Component formatting**: Clean object/array formatting with items on separate lines
- **Self-closing tags**: Include a space before closing (`/>`)
- **Trailing commas**: Used in multiline object and array literals

## TypeScript Best Practices

- **No explicit `any` types**: Always define proper interfaces
- **No unused variables**: Clean up unused variables and imports
- **Error handling**: Always handle errors with proper type checking
- **Type definitions**: Create interfaces for all data structures

## Enforcing Style

The project uses multiple configuration tools to enforce these standards:

1. **EditorConfig** (.editorconfig)
   - Provides basic editor settings across all editors
   - Handles indentation, line endings, etc.

2. **Prettier** (web/.prettierrc)
   - Handles detailed code formatting
   - Configured for consistent styling

3. **ESLint** (web/eslint.config.js)
   - Enforces code quality rules
   - Catches common errors and enforces conventions

4. **VS Code Settings** (.vscode/settings.json)
   - Configures VS Code to work with the above tools
   - Enables format-on-save functionality

## Developer Environment Setup

To ensure consistent formatting:

1. Install the recommended extensions for your editor:
   - EditorConfig
   - Prettier
   - ESLint

2. Configure your editor to format on save (VS Code settings are included in the project)

3. Before committing code:
   - Ensure all linting issues are resolved
   - Run `npm run lint` in the web directory to check for errors
