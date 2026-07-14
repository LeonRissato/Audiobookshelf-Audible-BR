# Audible BR → Audiobookshelf

Sistema para Windows que busca metadados no catálogo do **Audible Brasil** (`api.audible.com.br`, a mesma API usada pelos projetos [mkb79/Audible](https://github.com/mkb79/Audible) e [mkb79/audible-cli](https://github.com/mkb79/audible-cli)) e os aplica no **Audiobookshelf**. As buscas de catálogo são públicas — não é preciso login no Audible.

São duas ferramentas:

1. **Provider customizado** (`provider_server.py`) — o ABS ganha "Audible BR" como fonte de metadados no botão *Match*.
2. **Sincronização em lote** (`sync_library.py`) — varre a biblioteca inteira e atualiza tudo de uma vez.

## Instalação

1. Instale o [Python 3.9+](https://www.python.org/downloads/) (marque *Add Python to PATH*).
2. Dê dois cliques em `instalar.bat`.
3. Edite `config.json`:
   - `abs_url`: endereço do seu servidor (ex.: `http://localhost:13378`)
   - `abs_token`: token de API (ABS → Configurações → Usuários → seu usuário → API Token)
   - `provider_auth`: senha opcional para proteger o provider (deixe `""` para desativar)

## Provider customizado (botão Match do ABS)

1. Dê dois cliques em `provider.bat` — deixe a janela aberta.
2. No ABS: **Configurações → Item Metadata Utils → Custom Metadata Providers → Add**:
   - **Name:** Audible BR
   - **URL:** `http://IP_DO_PC:5557` (se o ABS roda no mesmo PC, `http://localhost:5557`; se roda em Docker no mesmo PC, use o IP da máquina, ex. `http://192.168.1.10:5557`)
   - **Authorization Header Value:** o valor de `provider_auth`, se você definiu um
3. Abra qualquer livro → **Match** → escolha o provider **Audible BR**.

Para iniciar o provider junto com o Windows, crie uma tarefa no Agendador de Tarefas apontando para `provider.bat` (ou coloque um atalho na pasta `shell:startup`).

## Tela de revisão manual (recomendado)

Dê dois cliques em `revisar.bat` — abre `http://localhost:5558` no navegador.

A tela mostra um livro por vez: à esquerda, o que está no ABS hoje; à direita, os candidatos do Audible BR com capa, narrador, série e duração. Clique em **Usar este** no correto e ela avança para o próximo. Você pode filtrar (só itens sem ASIN / sem capa), refazer a busca com outro título e escolher se sobrescreve campos e capa.

## Sincronização em lote

Sempre roda primeiro em **simulação** (não altera nada):

```
sincronizar.bat
```

Revise a saída e então aplique:

```
sincronizar.bat --aplicar             (só preenche campos vazios)
sincronizar.bat --aplicar --capas     (também baixa capas faltantes)
sincronizar.bat --aplicar --sobrescrever   (substitui pelos dados do Audible)
sincronizar.bat --biblioteca "Audiobooks" --limite 20   (teste em 20 itens)
```

Como cada livro é localizado: se o item já tem **ASIN** no ABS, busca direta por ASIN; senão, busca por **título + autor** e escolhe o resultado mais parecido (mínimo de 55% de similaridade — abaixo disso o item é pulado e listado como "não encontrado").

## Arquivos

| Arquivo | Função |
| --- | --- |
| `audible_br.py` | Acesso ao catálogo Audible BR (compartilhado) |
| `provider_server.py` | Servidor do provider customizado |
| `sync_library.py` | Sincronização em lote via API do ABS |
| `config.json` | Suas credenciais e opções |
| `instalar.bat` / `provider.bat` / `sincronizar.bat` | Atalhos Windows |

## Dicas

- O campo `audible_region_host` permite trocar a região (ex.: `api.audible.com` para EUA).
- A simulação mostra exatamente quais campos mudariam em cada livro — use antes de qualquer `--aplicar --sobrescrever`.
- Se um livro casar errado na sincronização, corrija pelo botão *Match* do ABS usando o provider Audible BR (que mostra a lista para você escolher).
