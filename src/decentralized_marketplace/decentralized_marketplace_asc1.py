from pyteal import *
import algosdk

from src.marketplace_interfaces import EscrowInterface, ResellMarketplaceInterface


class SimpleMarketplaceASC1(EscrowInterface, ResellMarketplaceInterface):
    class Variables:
        escrow_address = Bytes("ESCROW_ADDRESS")
        asa_id = Bytes("ASA_ID")
        asa_price = Bytes("ASA_PRICE")
        asa_owner = Bytes("ASA_OWNER")
        app_state = Bytes("APP_STATE")
        app_admin = Bytes("APP_ADMIN")

    class AppMethods:
        initialize_escrow = "initializeEscrow"
        sell = "sell"
        buy = "buy"
        stop_selling = "stopSelling"

    class AppState:
        not_initialized = Int(0)
        active = Int(1)
        selling_in_progress = Int(2)

    def application_start(self):
        actions = Cond(
            [Txn.application_id() == Int(0), self.app_initialization()],
            [Txn.application_args[0] == Bytes(self.AppMethods.buy), self.buy()],
            [Txn.application_args[0] == Bytes(self.AppMethods.initialize_escrow), self.initialize_escrow()],
            [Txn.application_args[0] == Bytes(self.AppMethods.stop_selling), self.stop_selling()],
            [Txn.application_args[0] == Bytes(self.AppMethods.sell), self.sell()]
        )

        return actions

    def app_initialization(self):
        """
        CreateAppTxn with 3 arguments: asa_id, asa_owner, app_admin.
        :return:
        """
        return Seq([
            Assert(Txn.application_args.length() == Int(3)),
            App.globalPut(self.Variables.app_state, self.AppState.not_initialized),
            App.globalPut(self.Variables.asa_id, Btoi(Txn.application_args[0])),
            App.globalPut(self.Variables.asa_owner, Txn.application_args[1]),
            App.globalPut(self.Variables.app_admin, Txn.application_args[2]),
            Return(Int(1))
        ])

    def initialize_escrow(self):
        """
        Application call from the app_admin.
        :return:
        """
        not_valid_number_of_transactions = Global.group_size() != Int(1)
        escrow_address = App.globalGetEx(Int(0), self.Variables.escrow_address)

        setup_escrow = Seq([
            App.globalPut(self.Variables.escrow_address, Txn.application_args[1]),
            App.globalPut(self.Variables.app_state, self.AppState.active),
            Return(Int(1))
        ])

        not_admin = App.globalGet(self.Variables.app_admin) != Txn.sender()

        return Seq([
            escrow_address,
            If(Or(escrow_address.hasValue(),
                  not_admin,
                  not_valid_number_of_transactions)).Then(Return(Int(0))).Else(setup_escrow)
        ])

    def sell(self):
        """
        Single application call with 2 arguments.
        - method_name
        - price
        :return:
        """
        valid_number_of_transactions = Global.group_size() == Int(1)
        app_is_active = Or(App.globalGet(self.Variables.app_state) == self.AppState.active,
                           App.globalGet(self.Variables.app_state) == self.AppState.selling_in_progress)

        valid_seller = Txn.sender() == App.globalGet(self.Variables.asa_owner)
        valid_number_of_arguments = Txn.application_args.length() == Int(2)

        can_sell = And(valid_number_of_transactions,
                       app_is_active,
                       valid_seller,
                       valid_number_of_arguments)

        update_state = Seq([
            App.globalPut(self.Variables.asa_price, Btoi(Txn.application_args[1])),
            App.globalPut(self.Variables.app_state, self.AppState.selling_in_progress),
            Return(Int(1))
        ])

        return If(can_sell).Then(update_state).Else(Return(Int(0)))

    def buy(self):
        """
        Atomic transfer of 3 transactions:
        1. Application call.
        2. Payment from buyer to seller.
        3. Asset transfer from escrow to buyer.
        :return:
        """
        valid_number_of_transactions = Global.group_size() == Int(3)
        asa_is_on_sale = App.globalGet(self.Variables.app_state) == self.AppState.selling_in_progress

        valid_payment_to_seller = And(
            Gtxn[1].type_enum() == TxnType.Payment,
            Gtxn[1].receiver() == App.globalGet(self.Variables.asa_owner),
            Gtxn[1].amount() == App.globalGet(self.Variables.asa_price),
            Gtxn[1].sender() == Gtxn[0].sender(),
            Gtxn[1].sender() == Gtxn[2].asset_receiver()
        )

        valid_asa_transfer_from_escrow_to_buyer = And(
            Gtxn[2].type_enum() == TxnType.AssetTransfer,
            Gtxn[2].sender() == App.globalGet(self.Variables.escrow_address),
            Gtxn[2].xfer_asset() == App.globalGet(self.Variables.asa_id),
            Gtxn[2].asset_amount() == Int(1)
        )

        can_buy = And(valid_number_of_transactions,
                      asa_is_on_sale,
                      valid_payment_to_seller,
                      valid_asa_transfer_from_escrow_to_buyer)

        update_state = Seq([
            App.globalPut(self.Variables.asa_owner, Gtxn[0].sender()),
            App.globalPut(self.Variables.app_state, self.AppState.active),
            Return(Int(1))
        ])

        return If(can_buy).Then(update_state).Else(Return(Int(0)))

    def stop_selling(self):
        """
        Single application call.
        :return:
        """
        valid_number_of_transactions = Global.group_size() == Int(1)
        valid_caller = Txn.sender() == App.globalGet(self.Variables.asa_owner)
        app_is_initialized = App.globalGet(self.Variables.app_state) != self.AppState.not_initialized

        can_stop_selling = And(valid_number_of_transactions,
                               valid_caller,
                               app_is_initialized)

        update_state = Seq([
            App.globalPut(self.Variables.app_state, self.AppState.active),
            Return(Int(1))
        ])

        return If(can_stop_selling).Then(update_state).Else(Return(Int(0)))

    def approval_program(self):
        return self.application_start()

    def clear_program(self):
        return Return(Int(1))

    @property
    def global_schema(self):
        return algosdk.future.transaction.StateSchema(num_uints=3,
                                                      num_byte_slices=3)

    @property
    def local_schema(self):
        return algosdk.future.transaction.StateSchema(num_uints=0,
                                                      num_byte_slices=0)
