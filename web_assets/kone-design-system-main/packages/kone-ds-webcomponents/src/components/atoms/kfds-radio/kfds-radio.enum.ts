export enum RadioOrientation {
    Vertical = 'vertical',
    Horizontal = 'horizontal'
};

export enum RadioSize {
    Small = 'small',
    Medium = 'medium',
    Large = 'large'
};

export interface RadioOption {
    id: string;
    value: string;
    label: string;
    hintText: string;
};