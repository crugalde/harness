import argparse
import sys

def calculate_import_cost(usd_price: float, shipping_cost: float, exchange_rate: float = 950.0) -> dict:
    """
    Calcula el costo total de importación a Chile considerando arancel e IVA.
    Si el valor FOB (precio del producto) es menor a 41 USD, generalmente no paga impuestos (dependiendo de la naturaleza).
    Para simplificar y ser conservador, asumimos la regla general de aduanas:
    Valor CIF = USD Precio + Envío (asumimos seguro = 0 o incluido en envío)
    Arancel aduanero = 6% del CIF
    IVA = 19% del (CIF + Arancel)
    """
    cif_usd = usd_price + shipping_cost
    
    # Evaluar exención (compras menores a 41 USD usualmente exentas si son ocasionales)
    if usd_price < 41.0:
        arancel_usd = 0.0
        iva_usd = 0.0
        is_taxed = False
    else:
        arancel_usd = cif_usd * 0.06
        iva_usd = (cif_usd + arancel_usd) * 0.19
        is_taxed = True
        
    total_usd = cif_usd + arancel_usd + iva_usd
    total_clp = total_usd * exchange_rate
    
    return {
        "usd_price": usd_price,
        "shipping_cost": shipping_cost,
        "cif_usd": cif_usd,
        "arancel_usd": arancel_usd,
        "iva_usd": iva_usd,
        "total_usd": total_usd,
        "exchange_rate": exchange_rate,
        "total_clp": total_clp,
        "is_taxed": is_taxed
    }

def main():
    parser = argparse.ArgumentParser(description="Calculadora de costos de importación a Chile.")
    parser.add_argument("--usd", type=float, required=True, help="Precio del producto en USD (FOB).")
    parser.add_argument("--envio", type=float, default=0.0, help="Costo de envío en USD.")
    parser.add_argument("--usd-clp", type=float, default=950.0, help="Tipo de cambio USD a CLP (default: 950).")
    
    args = parser.parse_args()
    
    result = calculate_import_cost(args.usd, args.envio, args.usd_clp)
    
    print("\n--- RESUMEN DE IMPORTACIÓN A CHILE ---")
    print(f"Precio Producto (FOB): ${result['usd_price']:.2f} USD")
    print(f"Envío:                 ${result['shipping_cost']:.2f} USD")
    print(f"Valor CIF:             ${result['cif_usd']:.2f} USD")
    
    if result["is_taxed"]:
        print(f"Arancel Aduanero (6%): ${result['arancel_usd']:.2f} USD")
        print(f"IVA (19%):             ${result['iva_usd']:.2f} USD")
    else:
        print("Impuestos:             $0.00 USD (Exento por ser < $41 USD FOB)")
        
    print("--------------------------------------")
    print(f"Total a Pagar (USD):   ${result['total_usd']:.2f} USD")
    print(f"Tipo de Cambio:        ${result['exchange_rate']:.2f} CLP/USD")
    print(f"TOTAL ESTIMADO (CLP):  ${result['total_clp']:,.0f} CLP")
    print("--------------------------------------\n")

if __name__ == "__main__":
    main()
