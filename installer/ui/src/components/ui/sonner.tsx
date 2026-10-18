import {CheckCircle2, CircleAlert, Info, LoaderCircle} from 'lucide-react';
import {Toaster as Sonner, type ToasterProps} from 'sonner';

/** One accessible notification surface for native, protocol and UI operations. */
export function Toaster(props: ToasterProps) {
  return <Sonner position="top-right" closeButton visibleToasts={2} gap={10}
    offset={{top: 88, right: 24}} duration={4500}
    icons={{success: <CheckCircle2 size={18}/>, error: <CircleAlert size={18}/>,
      warning: <CircleAlert size={18}/>, info: <Info size={18}/>, loading: <LoaderCircle size={18} className="spin"/>}}
    toastOptions={{classNames: {toast: 'app-toast', description: 'toast-description'}}}
    {...props}/>;
}
