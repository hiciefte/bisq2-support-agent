// Learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom'

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  ChevronDown: ({ className }) => <svg className={className} data-testid="chevron-down-icon" />,
}))

// Mock Radix UI Dialog components
jest.mock('@radix-ui/react-dialog', () => ({
  Root: ({ children, open }) => (open ? <div role="dialog">{children}</div> : null),
  Portal: ({ children }) => <div>{children}</div>,
  Overlay: ({ children }) => <div>{children}</div>,
  Content: ({ children, ...props }) => <div role="dialog" {...props}>{children}</div>,
  Title: ({ children }) => <h2>{children}</h2>,
  Description: ({ children }) => <p>{children}</p>,
  Close: ({ children }) => <button>{children}</button>,
}))
