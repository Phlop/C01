# -*- coding: utf-8 -*-
from telethon import TelegramClient, events
from kafka_functions import KafkaManager
from kafka import KafkaConsumer
from kafka import KafkaProducer

import asyncio
import os, sys
import pathlib
import json
import argparse
import traceback
import datetime
import random
import time

from shutil import copyfile
from os import listdir
from os.path import isfile, join 

class GroupMetadataCollector():
    """
    Classe que encapsula o coletor de metadados de grupos do Telegram. Possui
    o método principal que realiza a leitura da entrada e faz a coleta de
    informações como o título, integrantes, criador e administrados dos grupos
    que o usuário faz parte.

    Atributos
    -----------
    group_blacklist : list
            Lista de ids de grupos que devem ser excluídos da coleta.

    Métodos
    -----------
    run()
        Faz a coleta dos metadados de grupos de Telegram de acordo
        com os parâmetros fornecidos na criação do objeto de coleta.
    """

    def __init__(self, args):
        """
        Inicializa o objeto

        Parâmetros
        ------------
            args : argparse.Namespace()
                Objeto com atributos que contém os argumentos de linha de
                comando fornecidos.
        """

        args_dict = vars(args)

        if args.json:
            with open(args.json) as json_file:
                json_args = json.load(json_file)
                args_dict.update(json_args)
        elif args.json_string:
            json_args = json.loads(args.json_string)
            args_dict.update(json_args)
        
        self.session_name          = args_dict["session_name"]
        if (args_dict["api_id"] == '' or args_dict["api_id"] == None) or (args_dict["api_hash"] == '' or args_dict["api_hash"] == None):
            keys_file = '/config/credentials_%s.json'%(self.session_name) 
            if os.path.isfile(keys_file):
                with open(keys_file, 'r') as fin:
                    keys_args = json.load(fin)
                    args_dict["api_id"]   = keys_args["api_id"]
                    args_dict["api_hash"] = keys_args["api_hash"]
                    args_dict["session_name"] = keys_args["session_name"]
            else:
                print('No credentials provided: api_id, api_hash\nUnable to connect to Telegram API...')
                sys.exit(1)
            
            
            
        if args_dict["write_mode"] not in ['both', 'file', 'kafka']:
            print('Save mode invalid <%s>!! Using <kafka> instead' % (
                args_dict["write_mode"]))
            args_dict["write_mode"] = 'kafka'
        
        
        self.write_mode              = args_dict["write_mode"]    
            
        self.group_blacklist       = args_dict["group_blacklist"]
        self.api_id                = args_dict["api_id"]
        self.api_hash              = args_dict["api_hash"]
        self.profile_pic           = args_dict["profile_pic"]
        self.profiles              = args_dict["profiles"]
        self.data_path             = '/data/'
        self.datalake              = args_dict["datalake"]
        self.bootstrap_servers     = args_dict["bootstrap_servers"]
        self.session_name          = args_dict["session_name"]

       
                
        if self.write_mode == 'kafka' or self.write_mode == 'both':
            self.save_file             = False
            self.save_kafka            = True
            self.kafka                 = KafkaManager()
            if len(args_dict["bootstrap_servers"]) > 1:
                self.bootstrap_servers     = args_dict["bootstrap_servers"]
                self.kafka.update_servers(self.bootstrap_servers )
            if len(args_dict["bootstrap_servers"]) == 1:
                self.bootstrap_servers     = args_dict["bootstrap_servers"][0].split(',')
                self.kafka.update_servers(self.bootstrap_servers )
            self.producer              = self.kafka.connect_kafka_producer()
        else:
            self.save_file             = True
            self.save_kafka            = False
        
        #SAVING CREDENTIALS FOR FUTURE
        with open('/config/credentials_%s.json'%(args_dict["session_name"])  , "w") as json_file:
            api_dict = dict()
            api_dict["api_id"]        = args_dict["api_id"]
            api_dict["api_hash"]      = args_dict["api_hash"]
            api_dict["session_name"]  = args_dict["session_name"]
            json.dump(api_dict, json_file)
        
        
    async def run(self):
        """
        Faz a coleta dos metadados de grupos de Telegram de acordo
        com os parâmetros fornecidos na criação do objeto de coleta.

        Parâmetros
        ------------
            profile_path : str
                Caminho para um profile alternativo do navegador
                utilizado na coleta.
        """
        now = datetime.datetime.now()
        new_folder = '/data/metadata_grupos_%s/' % (now.strftime('%Y-%m-%d_%H-%M-%S'))
        pathlib.Path(new_folder).mkdir(parents=True, exist_ok=True)
        pathlib.Path(os.path.join(new_folder, "profile_pics")).mkdir(parents=True, exist_ok=True)
        
        
        
        session_name =  '%s.session'%(self.session_name)
        if isfile( join(self.data_path, session_name) ):
            copyfile(join(self.data_path, session_name), session_name)
            
        async with TelegramClient(session_name, self.api_id, self.api_hash) as client:
            
            print("Login na API do Telegram realizado com sucesso. Coletando grupos")
            if isfile(session_name):
                copyfile(session_name, join(self.data_path, session_name))
                
            async for dialog in client.iter_dialogs():
                WAIT_TIME = random.randint(10, 25)
                await asyncio.sleep(WAIT_TIME)
                if (
                    (not (dialog.is_group or dialog.is_channel) ) or 
                    (dialog.title in self.group_blacklist) or
                    str(abs(dialog.id)) in self.group_blacklist):
                        continue
                
                group = {}

                creator_id = None
                #TODO: check what kind is and dont know how to get creator
                group['grupo_id'] = dialog.entity.id
                # group['creator'] = creator
                # group['kind'] = kind
                group['criacao'] = dict()
                group['criacao']['criado_em'] = dialog.entity.date.strftime('%Y-%m-%d %H:%M:%S')
                group['criacao']['timestamp'] = int(datetime.datetime.timestamp(dialog.entity.date))
                group['titulo'] = dialog.entity.title
                group['dia_coleta'] = now.strftime('%Y-%m-%d')
                
                if dialog.is_channel:  groupType = "channel"
                if dialog.is_group:    groupType = "group"
                group['tipo'] = groupType
               
                print(group)
                
                participants = list()
                if dialog.is_group and self.profiles:
                    async for member in client.iter_participants(dialog):
                        user = dict()
                        #TODO: changed some stuff here.
                        user['user_id'] = member.id
                        user['username'] = member.username
                        user['first_name'] = member.first_name
                        user['last_name'] = member.last_name
                        user['number'] = member.phone
                        user['isBot'] = member.bot
                        user['profile_pic'] = None
                            
                        
                        if self.profile_pic:
                            user['profile_pic'] = os.path.join(new_folder, "profile_pics", str(member.id) + '.jpg')
                            if not os.path.isfile(user['profile_pic']):
                                try:
                                    await client.download_profile_photo(member, user['profile_pic'])
                                except:
                                    print('Error downloading profile picture for', member.id, member.username)
                            
                        participants.append(user)
                group['members'] = participants
                
                
                if self.save_kafka:
                    topic = self.kafka.get_topic('telegram' , 'grupo')
                    json_dump_object = json.dumps(group)
                    self.kafka.publish_kafka_message(self.producer, topic, 'raw', json_dump_object)
                
                
                if self.save_file:
                    filename = os.path.join(new_folder, 'grupos.json')
                    with open(filename, 'a') as json_file:
                        json.dump(group, json_file)
                        print('', file=json_file)
                
                
                
def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

async def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--group_blacklist", nargs="+",
                        help="Lista de ids de grupos que devem ser excluídos"
                        " da coleta", default=[])

    parser.add_argument("--profile_pic",  type=str2bool, nargs='?',
                        const=True, default=False,
                        help="Flag para baixar ou não as fotos de perfil dos usuários ")
                        
    parser.add_argument("--profiles", type=str2bool, nargs='?',
                        const=True, default=True,
                        help="Flag para listar quem sÃo os usuários ")
                        
    parser.add_argument("-w", "--write_mode", type=str,
                        help="Modo de salvamento das mensagens no arquivos de saida(\'both\', \'file\', \'kafka\'). ", default='kafka')

    parser.add_argument("--api_id", type=str,
                        help="ID da API de Coleta gerado em my.telegram.org (Dado sensível)", default='')

    parser.add_argument("--api_hash", type=str,
                        help="Hash da API de Coleta gerado em my.telegram.org (Dado sensível)", default='')

    parser.add_argument("-j", "--json", type=str,
                        help="Caminho para um arquivo json de configuração de "
                        "execução. Individualmente, as opções presentes no "
                        "arquivo sobescreveram os argumentos de linha de "
                        "comando, caso eles sejam fornecidos.")

    parser.add_argument("--json_string", type=str,
                        help="String contendo um json de configuração de"
                        " execução. Individualmente, as opções presentes no "
                        "arquivo sobescreveram os argumentos de linha de "
                        "comando, caso eles sejam fornecidos.")

    parser.add_argument("--datalake", type=str,
                        help="Local para salvar as midias",
                        default='/datalake/ufmg/telegram/')
                        
    parser.add_argument("--session_name", type=str,
                        help="Nome de secao para autenticacao da API do Telegram. Gera um arquivo <seciton_name>.session autorizando a conta a usar  a API",
                        default='telegram_api')
                        
    parser.add_argument("--bootstrap_servers", nargs="+",
                        help="Lista de endereço para conexão dos servers Kafka"
                        " (Brokers)", default=[])
    args = parser.parse_args()
    
    print("Inicializando coletor de metadados")
    try:
        collector = GroupMetadataCollector(args)
        await collector.run()
    except Exception as e:
        #TODO: Print log file
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())


