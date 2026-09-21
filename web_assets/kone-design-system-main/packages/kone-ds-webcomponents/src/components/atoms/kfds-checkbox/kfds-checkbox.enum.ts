export enum CheckboxOrientation {
    Vertical = 'vertical',
    Horizontal = 'horizontal'
};

export enum CheckboxSize {
    Small = 'small',
    Medium = 'medium',
    Large = 'large'
};

export interface CheckboxOption {
    id: string;
    value: string;
    label: string;
    hintText: string;
};