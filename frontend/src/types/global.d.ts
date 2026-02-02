type BootstrapModalInstance = {
  show: () => void;
  hide: () => void;
};

type BootstrapModalStatic = {
  new (element: Element): BootstrapModalInstance;
  getInstance: (element: Element) => BootstrapModalInstance | null;
};

declare const bootstrap: {
  Modal: BootstrapModalStatic;
};
