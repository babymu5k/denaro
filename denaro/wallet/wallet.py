import argparse
import asyncio
import os
import sys
from decimal import Decimal

import pickledb
import requests
from fastecdsa import keys, curve

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, dir_path + "/../..")

from denaro import Database, node
from denaro.transactions import Transaction, TransactionOutput

from denaro.constants import CURVE
from denaro.helpers import point_to_string, sha256

Database.credentials = {
    'user': os.environ.get('DENARO_DATABASE_USER', 'denaro'),
    'password': os.environ.get('DENARO_DATABASE_PASSWORD', '')
}


async def create_transaction(private_keys, receiving_address, amount):
    denaro_database: Database = await Database.get()
    amount = Decimal(amount)
    inputs = []
    for private_key in private_keys:
        address = point_to_string(keys.get_public_key(private_key, curve.P256))
        inputs.extend(await denaro_database.get_spendable_outputs(address, check_pending_txs=True))
        if sum(input.amount for input in inputs) >= amount:
            break
    if not inputs:
        raise Exception('No spendable outputs')

    if sum(input.amount for input in inputs) < amount:
        raise Exception(f"Error: You don\'t have enough funds")

    most_amount = sorted(inputs, key=lambda item: item.amount, reverse=True)

    transaction_inputs = []

    for i, tx_input in enumerate(most_amount):
        transaction_inputs.append(tx_input)
        transaction_amount = sum(input.amount for input in transaction_inputs)
        if transaction_amount >= amount:
            break

    transaction_amount = sum(input.amount for input in transaction_inputs)

    transaction = Transaction(transaction_inputs, [TransactionOutput(receiving_address, amount=amount)])
    if transaction_amount > amount:
        transaction.outputs.append(TransactionOutput(address, transaction_amount - amount))

    transaction.sign(private_keys)

    await denaro_database.add_pending_transaction(transaction)
    requests.get('https://denaro-node.gaetano.eu.org/push_tx', {'tx_hex': transaction.hex()}, timeout=10)
    return transaction


async def main():
    parser = argparse.ArgumentParser(description='Denaro wallet')
    parser.add_argument('command', metavar='command', type=str, help='action to do with the wallet', choices=['createwallet', 'send', 'balance'])
    parser.add_argument('-to', metavar='recipient', type=str, required=False)
    parser.add_argument('-d', metavar='amount', type=str, required=False)

    args = parser.parse_args()
    db = pickledb.load(f'{dir_path}/wallet.json', True)
    denaro_database: Database = await Database.get()
    node.main.db = denaro_database

    command = args.command

    if command == 'createwallet':
        private_keys = db.get('private_keys') or []
        private_key = keys.gen_private_key(CURVE)
        private_keys.append(private_key)
        db.set('private_keys', private_keys)

        public_key = keys.get_public_key(private_key, curve.P256)
        address = point_to_string(public_key)

        print(f'Private key: {hex(private_key)}\nAddress: {address}')
    elif command == 'balance':
        private_keys = db.get('private_keys') or []
        for private_key in private_keys:
            public_key = keys.get_public_key(private_key, curve.P256)
            address = point_to_string(public_key)
            balance = await denaro_database.get_address_balance(address)
            pending_balance = await denaro_database.get_address_balance(address, True)
            print(f'Address: {address}\nBalance: {balance}{f" ({pending_balance - balance} pending)" if pending_balance - balance != 0 else ""}')
    elif command == 'send':
        parser = argparse.ArgumentParser()
        parser.add_argument('command', metavar='command', type=str, help='action to do with the wallet')
        parser.add_argument('-to', metavar='recipient', type=str, dest='recipient', required=True)
        parser.add_argument('-d', metavar='amount', type=str, dest='amount', required=True)

        args = parser.parse_args()
        receiver = args.recipient
        amount = args.amount

        tx = await create_transaction(db.get('private_keys'), receiver, amount)
        print(f'Transaction pushed. Transaction hash: {sha256(tx.hex())}')


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
