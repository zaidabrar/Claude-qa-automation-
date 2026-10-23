import { query } from "./db";

export interface City {
  id: number;
  name: string;
  state: string;
  tier: number;
  lat: number;
  lng: number;
  rto_pct: number;
}

export interface Car {
  id: number;
  make: string;
  model: string;
  variant: string;
  fuel: string;
  transmission: string;
  ex_showroom_price: number;
  colors: string[];
}

export function listCities(): Promise<City[]> {
  return query<City>("SELECT * FROM cities ORDER BY tier, name");
}

export function listCars(): Promise<Car[]> {
  return query<Car>("SELECT * FROM cars ORDER BY make, model, ex_showroom_price");
}
