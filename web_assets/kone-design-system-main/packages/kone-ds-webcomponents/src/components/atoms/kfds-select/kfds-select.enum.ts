export enum SelectSize {
    Small = 'small',
    Medium = 'medium',
    Large = 'large',
    Inline = 'inline'
};

export enum SelectShape {
    Rounded = 'rounded',
    Pill = 'pill'
};

export interface selectOption {
    value: string;
    label: string;
};
