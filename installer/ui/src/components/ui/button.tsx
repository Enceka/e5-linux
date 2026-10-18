import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../utils';
const variants = cva('ui-button inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 h-10 px-4 py-2', {variants: {variant: {
  default: 'bg-primary text-primary-foreground hover:opacity-90',
  outline: 'border border-border bg-card hover:bg-muted text-foreground',
  ghost: 'hover:bg-muted text-foreground',
  destructive: 'bg-destructive text-white hover:opacity-90'
}}, defaultVariants: {variant: 'default'}});
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> {asChild?: boolean}
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({className, variant, asChild = false, ...props}, ref) => {
  const Component = asChild ? Slot : 'button';
  return <Component ref={ref} className={cn(variants({variant, className}))} {...props}/>;
});
Button.displayName = 'Button';
