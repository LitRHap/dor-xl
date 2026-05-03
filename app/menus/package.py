import json
import sys

import requests
from app.service.auth import AuthInstance
from app.client.engsel import get_family, get_package, get_addons, get_package_details, send_api_request, unsubscribe
from app.client.ciam import get_auth_code
from app.service.bookmark import BookmarkInstance
from app.client.purchase.redeem import settlement_bounty, settlement_loyalty, bounty_allotment
from app.menus.util import clear_screen, pause, display_html
from app.client.purchase.qris import show_qris_payment
from app.client.purchase.ewallet import show_multipayment
from app.client.purchase.balance import settlement_balance
from app.type_dict import PaymentItem
from app.menus.purchase import purchase_n_times, purchase_n_times_by_option_code
from app.menus.util import format_quota_byte
from app.service.decoy import DecoyInstance
from app.console import console, print_cyber_panel, cyber_input, loading_animation, print_step
from rich.table import Table
from rich.panel import Panel

def show_package_details(api_key, tokens, package_option_code, is_enterprise, option_order = -1):
    active_user = AuthInstance.active_user
    subscription_type = active_user.get("subscription_type", "")

    clear_screen()

    with loading_animation("Fetching package details..."):
        package = get_package(api_key, tokens, package_option_code)

    if not package:
        console.print("[error]Failed to load package details.[/]")
        pause()
        return False

    price = package["package_option"]["price"]
    detail = display_html(package["package_option"]["tnc"])
    validity = package["package_option"]["validity"]

    option_name = package.get("package_option", {}).get("name","")
    family_name = package.get("package_family", {}).get("name","")
    variant_name = package.get("package_detail_variant", "").get("name","")

    title = f"{family_name} - {variant_name} - {option_name}".strip()

    family_code = package.get("package_family", {}).get("package_family_code","")
    parent_code = package.get("package_addon", {}).get("parent_code","")
    if parent_code == "":
        parent_code = "N/A"

    token_confirmation = package["token_confirmation"]
    ts_to_sign = package["timestamp"]
    payment_for = package["package_family"]["payment_for"]

    payment_items = [
        PaymentItem(
            item_code=package_option_code,
            product_type="",
            item_price=price,
            item_name=f"{variant_name} {option_name}".strip(),
            tax=0,
            token_confirmation=token_confirmation,
        )
    ]

    # Details Table
    details_table = Table(show_header=False, box=None, padding=(0, 2))
    details_table.add_column("Key", style="neon_cyan", justify="right")
    details_table.add_column("Value", style="bold white")

    details_table.add_row("Nama:", title)
    details_table.add_row("Harga:", f"Rp {price}")
    details_table.add_row("Payment For:", str(payment_for))
    details_table.add_row("Masa Aktif:", str(validity))
    details_table.add_row("Point:", str(package['package_option']['point']))
    details_table.add_row("Plan Type:", package['package_family']['plan_type'])
    details_table.add_row("Family Code:", family_code)
    details_table.add_row("Parent Code:", parent_code)

    print_cyber_panel(details_table, title="DETAIL PAKET")

    benefits = package["package_option"]["benefits"]
    if benefits and isinstance(benefits, list):
        benefit_table = Table(show_header=True, header_style="neon_pink", box=None)
        benefit_table.add_column("Benefit Name", style="white")
        benefit_table.add_column("Total/Quota", style="neon_green")
        benefit_table.add_column("Type", style="dim")

        for benefit in benefits:
            total_display = ""
            data_type = benefit['data_type']
            if data_type == "VOICE" and benefit['total'] > 0:
                total_display = f"{benefit['total']/60} menit"
            elif data_type == "TEXT" and benefit['total'] > 0:
                total_display = f"{benefit['total']} SMS"
            elif data_type == "DATA" and benefit['total'] > 0:
                if benefit['total'] > 0:
                    quota = int(benefit['total'])
                    # It is in byte, make it in GB
                    if quota >= 1_000_000_000:
                        quota_gb = quota / (1024 ** 3)
                        total_display = f"{quota_gb:.2f} GB"
                    elif quota >= 1_000_000:
                        quota_mb = quota / (1024 ** 2)
                        total_display = f"{quota_mb:.2f} MB"
                    elif quota >= 1_000:
                        quota_kb = quota / 1024
                        total_display = f"{quota_kb:.2f} KB"
                    else:
                        total_display = f"{quota} B"
            elif data_type not in ["DATA", "VOICE", "TEXT"]:
                total_display = f"{benefit['total']}"

            if benefit["is_unlimited"]:
                total_display = "Unlimited"

            benefit_table.add_row(benefit['name'], total_display, data_type)

        print_cyber_panel(benefit_table, title="BENEFITS")

    with loading_animation("Checking addons..."):
        addons = get_addons(api_key, tokens, package_option_code)

    # print(f"Addons:\n{json.dumps(addons, indent=2)}") # Reduced noise

    console.print(Panel(detail, title="[neon_pink]SnK MyXL[/]", border_style="dim white"))

    in_package_detail_menu = True
    while in_package_detail_menu:
        # Options Menu
        menu_table = Table(show_header=False, box=None)
        menu_table.add_row("1", "Beli dengan Pulsa")
        menu_table.add_row("2", "Beli dengan E-Wallet")
        menu_table.add_row("3", "Bayar dengan QRIS")
        menu_table.add_row("4", "Pulsa + Decoy")
        menu_table.add_row("5", "Pulsa + Decoy V2")
        menu_table.add_row("6", "QRIS + Decoy (+1K)")
        menu_table.add_row("7", "QRIS + Decoy V2")
        menu_table.add_row("8", "Pulsa N kali")

        # Sometimes payment_for is empty, so we set default to BUY_PACKAGE
        if payment_for == "":
            payment_for = "BUY_PACKAGE"

        if payment_for == "REDEEM_VOUCHER":
            menu_table.add_row("B", "Ambil sebagai bonus")
            menu_table.add_row("BA", "Kirim bonus")
            menu_table.add_row("L", "Beli dengan Poin")

        if option_order != -1:
            menu_table.add_row("0", "Tambah ke Bookmark")
        menu_table.add_row("00", "Kembali ke daftar paket")

        print_cyber_panel(menu_table, title="ACTIONS")

        choice = cyber_input("Pilihan")
        if choice == "00":
            return False
        elif choice == "0" and option_order != -1:
            # Add to bookmark
            success = BookmarkInstance.add_bookmark(
                family_code=package.get("package_family", {}).get("package_family_code",""),
                family_name=package.get("package_family", {}).get("name",""),
                is_enterprise=is_enterprise,
                variant_name=variant_name,
                option_name=option_name,
                order=option_order,
            )
            if success:
                console.print("[neon_green]Paket berhasil ditambahkan ke bookmark.[/]")
            else:
                console.print("[warning]Paket sudah ada di bookmark.[/]")
            pause()
            continue

        elif choice == '1':
            settlement_balance(
                api_key,
                tokens,
                payment_items,
                payment_for,
                True
            )
            pause()
            return True
        elif choice == '2':
            show_multipayment(
                api_key,
                tokens,
                payment_items,
                payment_for,
                True,
            )
            pause()
            return True
        elif choice == '3':
            show_qris_payment(
                api_key,
                tokens,
                payment_items,
                payment_for,
                True,
            )
            pause()
            return True
        elif choice == '4':
            # Balance with Decoy
            decoy = DecoyInstance.get_decoy("balance")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            overwrite_amount = price + decoy_package_detail["package_option"]["price"]
            res = settlement_balance(
                api_key,
                tokens,
                payment_items,
                payment_for,
                False,
                overwrite_amount=overwrite_amount,
            )

            if res and res.get("status", "") != "SUCCESS":
                error_msg = res.get("message", "Unknown error")
                if "Bizz-err.Amount.Total" in error_msg:
                    error_msg_arr = error_msg.split("=")
                    valid_amount = int(error_msg_arr[1].strip())

                    print(f"Adjusted total amount to: {valid_amount}")
                    res = settlement_balance(
                        api_key,
                        tokens,
                        payment_items,
                        payment_for,
                        False,
                        overwrite_amount=valid_amount,
                    )
                    if res and res.get("status", "") == "SUCCESS":
                        console.print("[neon_green]Purchase successful![/]")
            else:
                console.print("[neon_green]Purchase successful![/]")
            pause()
            return True
        elif choice == '5':
            # Balance with Decoy v2 (use token confirmation from decoy)
            decoy = DecoyInstance.get_decoy("balance")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            overwrite_amount = price + decoy_package_detail["package_option"]["price"]
            res = settlement_balance(
                api_key,
                tokens,
                payment_items,
                "🤫",
                False,
                overwrite_amount=overwrite_amount,
                token_confirmation_idx=1
            )

            if res and res.get("status", "") != "SUCCESS":
                error_msg = res.get("message", "Unknown error")
                if "Bizz-err.Amount.Total" in error_msg:
                    error_msg_arr = error_msg.split("=")
                    valid_amount = int(error_msg_arr[1].strip())

                    print(f"Adjusted total amount to: {valid_amount}")
                    res = settlement_balance(
                        api_key,
                        tokens,
                        payment_items,
                        "🤫",
                        False,
                        overwrite_amount=valid_amount,
                        token_confirmation_idx=-1
                    )
                    if res and res.get("status", "") == "SUCCESS":
                        console.print("[neon_green]Purchase successful![/]")
            else:
                console.print("[neon_green]Purchase successful![/]")
            pause()
            return True
        elif choice == '6':
            # QRIS decoy + Rpx
            decoy = DecoyInstance.get_decoy("qris")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            console.print(Panel(
                f"Harga Paket Utama: Rp {price}\nHarga Paket Decoy: Rp {decoy_package_detail['package_option']['price']}\n\nSilahkan sesuaikan amount (trial & error, 0 = malformed)",
                title="DECOY QRIS INFO",
                border_style="warning"
            ))

            show_qris_payment(
                api_key,
                tokens,
                payment_items,
                "SHARE_PACKAGE",
                True,
                token_confirmation_idx=1
            )

            pause()
            return True
        elif choice == '7':
            # QRIS decoy + Rp0
            decoy = DecoyInstance.get_decoy("qris0")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            console.print(Panel(
                f"Harga Paket Utama: Rp {price}\nHarga Paket Decoy: Rp {decoy_package_detail['package_option']['price']}\n\nSilahkan sesuaikan amount (trial & error, 0 = malformed)",
                title="DECOY QRIS INFO",
                border_style="warning"
            ))

            show_qris_payment(
                api_key,
                tokens,
                payment_items,
                "SHARE_PACKAGE",
                True,
                token_confirmation_idx=1
            )

            pause()
            return True
        elif choice == '8':
            #Pulsa N kali
            use_decoy_for_n_times = cyber_input("Use decoy package? (y/n)").strip().lower() == 'y'
            n_times_str = cyber_input("Enter number of times to purchase (e.g., 3)").strip()

            delay_seconds_str = cyber_input("Enter delay between purchases in seconds (e.g., 25)").strip()
            if not delay_seconds_str.isdigit():
                delay_seconds_str = "0"

            try:
                n_times = int(n_times_str)
                if n_times < 1:
                    raise ValueError("Number must be at least 1.")
            except ValueError:
                console.print("[error]Invalid number entered. Please enter a valid integer.[/]")
                pause()
                continue
            purchase_n_times_by_option_code(
                n_times,
                option_code=package_option_code,
                use_decoy=use_decoy_for_n_times,
                delay_seconds=int(delay_seconds_str),
                pause_on_success=False,
                token_confirmation_idx=1
            )
        elif choice.lower() == 'b':
            settlement_bounty(
                api_key=api_key,
                tokens=tokens,
                token_confirmation=token_confirmation,
                ts_to_sign=ts_to_sign,
                payment_target=package_option_code,
                price=price,
                item_name=variant_name
            )
            pause()
            return True
        elif choice.lower() == 'ba':
            destination_msisdn = cyber_input("Masukkan nomor tujuan bonus (mulai dengan 62)").strip()
            bounty_allotment(
                api_key=api_key,
                tokens=tokens,
                ts_to_sign=ts_to_sign,
                destination_msisdn=destination_msisdn,
                item_name=option_name,
                item_code=package_option_code,
                token_confirmation=token_confirmation,
            )
            pause()
            return True
        elif choice.lower() == 'l':
            settlement_loyalty(
                api_key=api_key,
                tokens=tokens,
                token_confirmation=token_confirmation,
                ts_to_sign=ts_to_sign,
                payment_target=package_option_code,
                price=price,
            )
            pause()
            return True
        else:
            console.print("[warning]Purchase cancelled.[/]")
            return False
    pause()
    sys.exit(0)

def get_packages_by_family(
    family_code: str,
    is_enterprise: bool | None = None,
    migration_type: str | None = None
):
    api_key = AuthInstance.api_key
    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        console.print("[error]No active user tokens found.[/]")
        pause()
        return None

    packages = []

    with loading_animation("Fetching family packages..."):
        data = get_family(
            api_key,
            tokens,
            family_code,
            is_enterprise,
            migration_type
        )

    if not data:
        console.print("[error]Failed to load family data.[/]")
        pause()
        return None

    price_currency = "Rp"
    rc_bonus_type = data["package_family"].get("rc_bonus_type", "")
    if rc_bonus_type == "MYREWARDS":
        price_currency = "Poin"

    in_package_menu = True
    while in_package_menu:
        clear_screen()

        # Family Info Panel
        family_table = Table(show_header=False, box=None)
        family_table.add_column("Key", style="neon_cyan", justify="right")
        family_table.add_column("Value", style="bold white")

        family_table.add_row("Family Name:", data['package_family']['name'])
        family_table.add_row("Family Code:", family_code)
        family_table.add_row("Family Type:", data['package_family']['package_family_type'])
        family_table.add_row("Variant Count:", str(len(data['package_variants'])))

        print_cyber_panel(family_table, title="FAMILY INFO")

        # Packages List
        pkg_table = Table(show_header=True, header_style="neon_pink", box=None, padding=(0, 1))
        pkg_table.add_column("No", style="neon_green", justify="right", width=4)
        pkg_table.add_column("Package Name", style="bold white")
        pkg_table.add_colu
